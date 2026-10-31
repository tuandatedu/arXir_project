"""Standalone, Colab-ready assigned-range arXiv crawler.

This deliberately does NOT import unfinished common ids/io/metrics, corpus.py,
Semantic Scholar, or pipeline.py. It writes an interoperable corpus that the
other teammates can consume. Batch archives are atomic and resumable on Drive.

Run from REPOSITORY ROOT:
 python -m src.m1_crawling.run_arxiv_only --preview
 python -m src.m1_crawling.run_arxiv_only --next 2 --backup-dir /content/drive/MyDrive/arxiv-m1
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import time
import threading
from typing import Any

import psutil

from src.m1_crawling.arxiv_http import ArxivHTTP, ArxivHTTPError
from src.m1_crawling.assigned_ranges import RANGES, assigned_ids, range_ids
from src.m1_crawling.discover import API_URL, ATOM, _identifier, fetch_papers_by_ids, list_versions, PaperMeta
from src.m1_crawling.download import (
    cleanup_temp_archive, detect_archive_kind, download_source_archive, extract_tex_and_bib,
)
from src.m1_crawling.phase_tracking import append_metric_row, directory_size

LOG = logging.getLogger("arxiv-crawler")
TERMINAL = {"ok", "no_tex", "not_found"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    temp.replace(path)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0

class ResourceSampler:
    """Sample Colab process-tree CPU/RSS (1s) and crawler scratch disk (5s)."""
    def __init__(self, path: Path):
        self.path = path
        self.root_pid = int(os.environ.get("M1_METRICS_ROOT_PID", os.getpid()))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="arxiv-metrics", daemon=True)
        self.rss_total = 0
        self.rss_samples = 0
        self.peak_rss_bytes = 0
        self.peak_scratch_bytes = 0
        self.cpu_samples: list[float] = []
        self._previous_cpu: dict[int, float] = {}
        self._previous_cpu_at: float | None = None

    def _loop(self) -> None:
        count = 0
        while not self._stop.is_set():
            try:
                try:
                    root = psutil.Process(self.root_pid)
                    processes = [root, *root.children(recursive=True)]
                except psutil.Error:
                    processes = [psutil.Process()]
                memory = 0
                current_cpu = {}
                now = time.monotonic()
                cpu_total = 0.0
                for process in processes:
                    try:
                        memory += process.memory_info().rss
                        times = process.cpu_times()
                        used = times.user + times.system
                        current_cpu[process.pid] = used
                        if process.pid in self._previous_cpu and self._previous_cpu_at is not None:
                            cpu_total += max(0.0, used - self._previous_cpu[process.pid]) * 100.0 / max(
                                now - self._previous_cpu_at, 1e-6
                            )
                    except psutil.Error:
                        continue
                self.rss_total += memory
                self.rss_samples += 1
                self.peak_rss_bytes = max(self.peak_rss_bytes, memory)
                if self._previous_cpu_at is not None:
                    self.cpu_samples.append(cpu_total)
                self._previous_cpu = current_cpu
                self._previous_cpu_at = now
                if count % 5 == 0:
                    self.peak_scratch_bytes = max(self.peak_scratch_bytes, _size(self.path))
            except (OSError, psutil.Error):
                pass
            count += 1
            self._stop.wait(1.0)

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=6)
        scratch_peak = max(self.peak_scratch_bytes, _size(self.path))
        return {"peak_rss_bytes": self.peak_rss_bytes,
                "average_rss_bytes": round(self.rss_total / max(1, self.rss_samples)),
                "rss_samples": self.rss_samples,
                "average_cpu_percent": round(sum(self.cpu_samples) / len(self.cpu_samples), 2)
                if self.cpu_samples else 0,
                "peak_cpu_percent": round(max(self.cpu_samples, default=0), 2),
                "cpu_samples": len(self.cpu_samples),
                "sampled_peak_scratch_bytes": scratch_peak}



def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_restore(archive: Path, target: Path) -> None:
    # Archive is generated by us, but do not trust Drive files to be intact.
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            parts = Path(member.name).parts
            if (not parts or Path(member.name).is_absolute()
                    or any(part in ("..", "") for part in parts)
                    or not member.isfile() or member.size > 64 * 1024 * 1024):
                raise ValueError(f"Unsafe file in checkpoint: {member.name}")
            dest = target.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            inp = tf.extractfile(member)
            if inp is not None:
                with inp, dest.open("wb") as out:
                    shutil.copyfileobj(inp, out)


def _archive_batch(batch_dir: Path, backup: Path, batch_name: str, manifest: dict) -> None:
    backup.mkdir(parents=True, exist_ok=True)
    archive = backup / (batch_name + ".tar.gz")
    partial = backup / (batch_name + ".tar.gz.partial")
    try:
        with tarfile.open(partial, mode="w:gz") as tf:
            for file in sorted(batch_dir.rglob("*")):
                if file.is_file():
                    tf.add(file, arcname=file.relative_to(batch_dir).as_posix(), recursive=False)
        digest = _sha256(partial)
        partial.replace(archive)
        manifest["archive_bytes"] = archive.stat().st_size
        manifest["archive_sha256"] = digest
        # Manifest LAST is the completion marker; previous archive alone is not trusted.
        _write_json(backup / (batch_name + ".json"), manifest)
    finally:
        partial.unlink(missing_ok=True)


def _existing_manifest(backup: Path, name: str, expected_ids: list[str],
                       verify_checksum: bool = False) -> dict | None:
    archive, marker = backup / f"{name}.tar.gz", backup / f"{name}.json"
    if not archive.exists() or not marker.exists():
        return None
    try:
        manifest = _read_json(marker)
        if manifest.get("ids") != expected_ids or archive.stat().st_size != manifest.get("archive_bytes"):
            return None
        if verify_checksum and _sha256(archive) != manifest.get("archive_sha256"):
            return None
        return manifest
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def _has_error(manifest: dict) -> bool:
    return manifest.get("failed", 0) > 0


def _is_discovery_failed_checkpoint(backup: Path, name: str, manifest: dict) -> bool:
    """Detect batches where discovery failed globally, so normal resume retries them."""
    if manifest.get("discovery_error"):
        return True
    requested = int(manifest.get("requested", 0) or 0)
    if (requested == 0 or int(manifest.get("failed", 0) or 0) != requested
            or int(manifest.get("not_found", 0) or 0) != 0):
        return False
    archive = Path(backup) / f"{name}.tar.gz"
    try:
        with tarfile.open(archive, "r:gz") as tf:
            member = tf.extractfile("crawl_records.jsonl")
            if member is None:
                return False
            rows = [json.loads(line) for line in member if line.strip()]
    except (OSError, tarfile.TarError, KeyError, json.JSONDecodeError):
        return False
    return len(rows) == requested and all(
        row.get("status") == "error"
        and str(row.get("error") or "").startswith("discovery:")
        for row in rows
    )


def _enrich_revision_dates(metas: dict[str, PaperMeta], http: ArxivHTTP) -> None:
    """Fill intermediate revision dates with version-qualified Atom lookups.

    For v1 the submission date is known. For latest vN the API updated date is
    known. Query only v2..v(N-1) because v2 paper needs no extra API request.
    If arXiv does not expose an intermediate version, retain latest date and
    explicitly flag `revision_dates_complete=False` in `raw`.
    """
    needed: list[str] = []
    for paper in metas.values():
        if paper.latest_version > 2:
            needed.extend(f"{paper.arxiv_id}v{n}" for n in range(2, paper.latest_version))
    if not needed:
        return
    import xml.etree.ElementTree as ET
    intermediate: dict[str, dict[int, str]] = {}
    for i in range(0, len(needed), 80):
        chunk = needed[i:i + 80]
        with http.get(API_URL, params={"id_list": ",".join(chunk), "max_results": len(chunk)}) as r:
            root = ET.fromstring(r.content)
        for entry in root.findall(ATOM + "entry"):
            try:
                base, ver = _identifier(entry.findtext(ATOM + "id") or "")
            except ValueError:
                continue
            updated = (entry.findtext(ATOM + "updated") or "")[:10]
            if updated:
                intermediate.setdefault(base, {})[ver] = updated
    for paper in metas.values():
        if paper.latest_version <= 2:
            continue
        found = intermediate.get(paper.arxiv_id, {})
        dates = [found[v] for v in range(2, paper.latest_version) if v in found]
        paper.raw["revision_dates_complete"] = len(dates) == paper.latest_version - 2
        paper.raw["intermediate_version_dates"] = {str(k): v for k, v in found.items()
                                                  if 2 <= k < paper.latest_version}
        latest = paper.raw.get("atom_updated", "")
        paper.revised_dates = dates + ([latest] if latest else [])


def _crawl_one(paper_id: str, meta: PaperMeta | None, work: Path, http: ArxivHTTP,
               previous: dict | None = None) -> dict:
    start = time.monotonic()
    folder = work / "working" / paper_id.replace(".", "-")
    folder.mkdir(parents=True, exist_ok=True)
    if meta is None:
        record = {"arxiv_id": paper_id, "status": "not_found", "versions": [],
                  "error": None, "elapsed_sec": round(time.monotonic() - start, 3)}
        _write_json(folder / "status.json", record)
        return record

    _write_json(folder / "paper.json", asdict(meta))
    version_rows = []
    previous_versions = {
        row.get("version"): row for row in (previous or {}).get("versions", [])
        if isinstance(row, dict)
    }
    for version in list_versions(meta):
        v_dir = folder / f"v{version}"
        v_dir.mkdir(parents=True, exist_ok=True)
        old_version = previous_versions.get(version)
        if old_version and old_version.get("status") in ("ok", "no_tex"):
            # Keep successful source files intact. Check their existence so a
            # corrupted/incomplete checkpoint does not count as a success.
            old_files = old_version.get("files") or []
            valid = old_version["status"] == "no_tex" or (
                bool(old_files) and all(
                    (v_dir / "sources" / filename).is_file() for filename in old_files
                )
            )
            if valid:
                version_rows.append(old_version)
                continue
        # Only failed or missing versions reach the download path.
        shutil.rmtree(v_dir / "sources", ignore_errors=True)
        (v_dir / "empty.json").unlink(missing_ok=True)
        version_dates = meta.raw.get("intermediate_version_dates", {})
        date = (meta.submission_date if version == 1 else
                meta.raw.get("atom_updated", "") if version == meta.latest_version
                else version_dates.get(str(version)))
        # Publication-level title and authors can change across revisions.
        # Never claim that these are the original per-version title/authors.
        _write_json(v_dir / "metadata.json", {
            "arxiv_id": paper_id, "version": version,
            "versioned_id": f"{paper_id}v{version}",
            "updated_date": date or None,
            "date_source": ("atom_published" if version == 1 else
                            "atom_updated_latest" if version == meta.latest_version
                            else "atom_intermediate_version" if date else "unknown"),
            "title_latest": meta.title, "authors_latest": meta.authors,
            "title_authors_scope": "latest_publication_only",
        })
        temp_archive = v_dir / "download.tmp"
        vstart = time.monotonic()
        vr = {"version": version, "status": "error", "archive_kind": None,
              "archive_bytes": 0, "filtered_bytes": 0, "file_count": 0,
              "files": [], "reason": None, "elapsed_sec": None}
        try:
            download_source_archive(paper_id, version, temp_archive, http=http)
            vr["archive_bytes"] = temp_archive.stat().st_size
            kind = detect_archive_kind(temp_archive)
            vr["archive_kind"] = kind
            if kind in ("pdf", "empty"):
                vr["status"] = "no_tex"
                vr["reason"] = f"source_{kind}"
            else:
                sources_dir = v_dir / "sources"
                files = extract_tex_and_bib(temp_archive, sources_dir)
                vr["files"] = [p.relative_to(sources_dir).as_posix() for p in files]
                vr["file_count"] = len(files)
                vr["filtered_bytes"] = sum(p.stat().st_size for p in files)
                vr["status"] = "ok" if files else "no_tex"
                if not files:
                    vr["reason"] = "no_tex_bib_in_archive"
                    shutil.rmtree(sources_dir, ignore_errors=True)
        except ArxivHTTPError as exc:
            if exc.status_code in (404, 410):
                vr["status"] = "no_tex"
                vr["reason"] = f"source_http_{exc.status_code}"
            else:
                vr["reason"] = str(exc)
        except (ValueError, OSError, EOFError, tarfile.TarError) as exc:
            vr["reason"] = f"{type(exc).__name__}: {exc}"
            shutil.rmtree(v_dir / "sources", ignore_errors=True)
        finally:
            cleanup_temp_archive(temp_archive)
            vr["elapsed_sec"] = round(time.monotonic() - vstart, 3)
            _write_json(v_dir / "status.json", vr)
            if vr["status"] == "no_tex":
                _write_json(v_dir / "empty.json", {"empty": True, "reason": vr["reason"]})
            version_rows.append(vr)
        if vr["status"] == "error":
            LOG.warning("Error source %s v%d: %s", paper_id, version, vr["reason"])
    result = {
        "arxiv_id": paper_id,
        "status": ("error" if any(v["status"] == "error" for v in version_rows)
                   else "ok" if any(v["status"] == "ok" for v in version_rows) else "no_tex"),
        "versions": version_rows,
        "error": "; ".join(
            f"v{v['version']}: {v.get('reason') or 'unknown error'}"
            for v in version_rows if v["status"] == "error"
        ) or None,
        "elapsed_sec": round(time.monotonic() - start, 3),
    }
    _write_json(folder / "status.json", result)
    return result


def _make_paper_row(meta: PaperMeta) -> dict:
    return {"arxiv_id": meta.arxiv_id, "title": meta.title, "authors": meta.authors,
            "submission_date": meta.submission_date, "revised_dates": meta.revised_dates,
            "venue": meta.venue}

def _print_batch_summary(name: str, manifest: dict, paper_rows: list[dict],
                         references: dict[str, list[dict]] | None = None) -> None:
    print("\n" + "=" * 70)
    print(f"{name} - REFERENCES")
    print("=" * 70)

    if references is None:
        print("References have not been collected in this crawler.")
    else:
        for paper_id, records in references.items():
            print(f"\nPaper: {paper_id}")

            if not records:
                print("  No references found")
                continue

            for index, ref in enumerate(records, 1):
                print(f"  {index}. {ref.get('title', 'Unknown title')}")

    print("\n" + "=" * 70)
    print(f"{name} - CRAWL SUMMARY")
    print("=" * 70)
    print(f"Requested: {manifest['requested']}")
    print(f"Processed: {manifest['processed_this_run']}")
    print(f"Successful: {manifest['ok']}")
    print(f"No TeX: {manifest['no_tex']}")
    print(f"Not found: {manifest['not_found']}")
    print(f"Failed: {manifest['failed']}")
    print(f"Workers: {manifest['workers_this_run']}")

    print("\n" + "=" * 70)
    print(f"{name} - CHECKPOINT")
    print("=" * 70)
    print(f"Archive size: {manifest['archive_bytes'] / 1024**2:.2f} MiB")
    print(f"SHA256: {manifest['archive_sha256']}")
    print("=" * 70, flush=True)

def _collect_existing_statuses(work: Path, ids: list[str]) -> dict[str, dict]:
    existing = {}
    for pid in ids:
        path = work / "working" / pid.replace(".", "-") / "status.json"
        if path.exists():
            existing[pid] = _read_json(path)
    return existing


def _crawl_pending(paper_id: str, meta: PaperMeta | None, batch_work: Path,
                   http: ArxivHTTP, previous: dict | None,
                   discovery_error: str | None) -> dict:
    """Worker owns one paper folder; only the coordinator writes batch files."""
    if discovery_error and meta is None:
        record = {"arxiv_id": paper_id, "status": "error", "versions": [],
                  "error": "discovery: " + discovery_error, "elapsed_sec": 0}
        _write_json(batch_work / "working" / paper_id.replace(".", "-") /
                    "status.json", record)
        return record
    try:
        return _crawl_one(paper_id, meta, batch_work, http, previous=previous)
    except Exception as exc:
        record = {"arxiv_id": paper_id, "status": "error", "versions": [],
                  "error": f"{type(exc).__name__}: {exc}", "elapsed_sec": 0}
        _write_json(batch_work / "working" / paper_id.replace(".", "-") /
                    "status.json", record)
        LOG.exception("Unexpected crawler failure for %s", paper_id)
        return record


def _run_batch(ids: list[str], name: str, output_root: Path, backup_dir: Path,
               http: ArxivHTTP, verify_checksum: bool,
               retry_failed: bool, revision_dates: bool, workers: int = 1) -> dict:
    previous = _existing_manifest(backup_dir, name, ids, verify_checksum)
    retry_discovery = bool(
        previous and not retry_failed
        and _is_discovery_failed_checkpoint(backup_dir, name, previous)
    )
    if previous and not retry_discovery and (not retry_failed or not _has_error(previous)):
        print(f"[SKIP] {name} complete checkpoint: {previous.get('ok',0)} OK, "
              f"{previous.get('failed',0)} errors (use --retry-failed)", flush=True)
        return previous
    batch_work = output_root / name
    if batch_work.exists():
        shutil.rmtree(batch_work)
    batch_work.mkdir(parents=True)
    batch_started_at = _now()
    old_status: dict[str, dict] = {}
    if previous and retry_failed:
        _safe_restore(backup_dir / f"{name}.tar.gz", batch_work)
        old_status = _collect_existing_statuses(batch_work, ids)
    pending = [pid for pid in ids if pid not in old_status or old_status[pid]["status"] == "error"]
    LOG.info("%s pending %d/%d papers", name, len(pending), len(ids))
    sampler = ResourceSampler(batch_work)
    sampler.start()
    before = time.monotonic()
    requests_before, retries_before = http.request_count, http.retry_count
    lookup_start = time.monotonic()
    metas: dict[str, PaperMeta] = {}
    need_discovery = []
    # Recovery reuses the original metadata instead of re-requesting it.
    for pid in pending:
        saved = batch_work / "working" / pid.replace(".", "-") / "paper.json"
        if saved.is_file():
            try:
                metas[pid] = PaperMeta(**_read_json(saved))
                continue
            except (TypeError, ValueError, OSError, json.JSONDecodeError):
                LOG.warning("Invalid saved metadata for %s; rediscovering", pid)
        need_discovery.append(pid)
    discovery_error = None
    try:
        for i in range(0, len(need_discovery), 100):
            metas.update(fetch_papers_by_ids(need_discovery[i:i + 100], http=http))
        if revision_dates:
            try:
                _enrich_revision_dates({pid: metas[pid] for pid in need_discovery
                                        if pid in metas}, http)
            except Exception as exc:
                LOG.warning("Version date lookup failed (metadata kept): %s", exc)
                for pid in need_discovery:
                    meta = metas.get(pid)
                    if meta and meta.latest_version > 2:
                        meta.raw["revision_dates_complete"] = False
    except Exception as exc:
        # Failure discovering some IDs does not invalidate cached metadata.
        discovery_error = f"{type(exc).__name__}: {exc}"
        LOG.error("Discovery failed in %s: %s", name, discovery_error)
    discovery_sec = time.monotonic() - lookup_start

    statuses: dict[str, dict] = dict(old_status)
    if workers == 1:
        for index, pid in enumerate(pending, 1):
            statuses[pid] = _crawl_pending(pid, metas.get(pid), batch_work, http,
                                           old_status.get(pid), discovery_error)
            if index % 10 == 0 or index == len(pending):
                print(f"[{name}] {index}/{len(pending)} processed, "
                      f"{http.request_count - requests_before} HTTP requests", flush=True)
    else:
        # Parallelize at PAPER level. HTTP request starts share a pacing gate,
        # but workers can wait for responses and stream bodies concurrently.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arxiv-paper") as pool:
            futures = {
                pool.submit(_crawl_pending, pid, metas.get(pid), batch_work, http,
                            old_status.get(pid), discovery_error): pid
                for pid in pending
            }
            for index, future in enumerate(as_completed(futures), 1):
                pid = futures[future]
                statuses[pid] = future.result()
                if index % 10 == 0 or index == len(pending):
                    print(f"[{name}] {index}/{len(pending)} processed, "
                          f"{http.request_count - requests_before} HTTP requests", flush=True)

    ordered = [statuses[pid] for pid in ids]
    _write_jsonl(batch_work / "crawl_records.jsonl", ordered)
    # A metadata row per discovered publication, including old successful papers.
    paper_rows = []
    for pid in ids:
        path = batch_work / "working" / pid.replace(".", "-") / "paper.json"
        if path.exists():
            p = _read_json(path)
            paper_rows.append({key: p.get(key) for key in (
                "arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue")})
    _write_jsonl(batch_work / "papers.jsonl", paper_rows)
    resource_metrics = sampler.finish()
    manifest = {"batch": name, "created_at": _now(), "ids": ids,
                "requested": len(ids), "processed_this_run": len(pending),
                "workers_this_run": workers,
                "ok": sum(x["status"] == "ok" for x in ordered),
                "no_tex": sum(x["status"] == "no_tex" for x in ordered),
                "not_found": sum(x["status"] == "not_found" for x in ordered),
                "failed": sum(x["status"] == "error" for x in ordered),
                "discovery_error": discovery_error,
                "api_requests_this_run": http.request_count - requests_before,
                "api_retries_this_run": http.retry_count - retries_before,
                "discovery_seconds_this_run": round(discovery_sec, 3),
                "runtime_seconds_this_run": round(time.monotonic() - before, 3),
                "input_archive_bytes": sum(v.get("archive_bytes", 0) for p in ordered for v in p["versions"]),
                "filtered_source_bytes": sum(v.get("filtered_bytes", 0) for p in ordered for v in p["versions"]),
                "work_dir_bytes_before_packaging": _size(batch_work),
                **resource_metrics}
    _write_json(batch_work / "metrics.json", manifest)
    start_upload = time.monotonic()
    _archive_batch(batch_work, backup_dir, name, manifest)
    manifest["archive_seconds"] = round(time.monotonic() - start_upload, 3)
    # Always keep an explicit archived manifest describing backup duration.
    _write_json(backup_dir / (name + ".json"), manifest)
    append_metric_row(backup_dir, {
        "phase": "arxiv_crawl",
        "batch": name,
        "started_at_utc": batch_started_at,
        "finished_at_utc": _now(),
        "elapsed_seconds": manifest["runtime_seconds_this_run"],
        "papers_requested": len(ids),
        "papers_processed": len(pending),
        "discovery_seconds": manifest["discovery_seconds_this_run"],
        "average_cpu_percent": resource_metrics["average_cpu_percent"],
        "peak_cpu_percent": resource_metrics["peak_cpu_percent"],
        "cpu_samples": resource_metrics["cpu_samples"],
        "peak_rss_bytes": resource_metrics["peak_rss_bytes"],
        "average_rss_bytes": resource_metrics["average_rss_bytes"],
        "rss_samples": resource_metrics["rss_samples"],
        "persistent_output_bytes": directory_size(backup_dir),
        "sampled_peak_scratch_bytes": resource_metrics["sampled_peak_scratch_bytes"],
        "status": "partial" if manifest["failed"] else "ok",
    })
    _print_batch_summary(name, manifest, paper_rows)

    shutil.rmtree(batch_work)
    return manifest


def verify_boundaries(http: ArxivHTTP) -> None:
    """Fail closed if the inferred 5000-ID cross-month boundaries are wrong."""
    probes: list[str] = []
    for item in RANGES:
        if item.cross_month_limit:
            month = item.first[:4]
            probes.extend([f"{month}.{item.cross_month_limit:05d}",
                           f"{month}.{item.cross_month_limit + 1:05d}"])
    fetched = fetch_papers_by_ids(probes, http=http)
    incorrect = [(id, id in fetched) for i, id in enumerate(probes)
                 if (i % 2 == 0 and id not in fetched)
                 or (i % 2 == 1 and id in fetched)]
    if incorrect:
        raise RuntimeError(f"Cross-month limits inferred from 5000 papers appear wrong: {incorrect}. "
                           "STOP and confirm the last monthly sequence numbers.")
    print("Boundary probe passed: both inferred month-end IDs found, next IDs absent.")


def build_batches(ids: list[str], batch_size: int) -> list[tuple[str, list[str]]]:
    return [(f"batch_{n:05d}", ids[i:i + batch_size])
            for n, i in enumerate(range(0, len(ids), batch_size))]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--range", type=int, default=0, choices=range(6), dest="range_number",
                   help="0=all 5 ranges, 1..5=one student's range")
    p.add_argument("--batch-size", type=int, default=50,
                   help="Number of papers per checkpoint (keep same on resume!)")
    p.add_argument("--next", type=int, default=2, metavar="N",
                   help="Process next N unfinished batches, 0=all (default: 2)")
    p.add_argument("--batch-start", type=int, default=None,
                   help="Optional absolute batch offset within selected range")
    p.add_argument("--output-root", type=Path, default=Path("/content/arxiv_scratch")
                   if Path("/content").is_dir() else Path("data/crawler_scratch"))
    p.add_argument("--backup-dir", type=Path, default=Path("data/crawler_backups"),
                   help="Persistent Drive folder; crucial for Colab resume")
    p.add_argument("--delay", type=float, default=3.1,
                   help="arXiv pacing: >=3 seconds between ALL requests")
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--workers", type=int, default=1,
                   help="Paper workers (1..4). Request starts share one global 3.1s pacing gate.")
    p.add_argument("--retry-failed", action="store_true",
                   help="Reopen checkpoint and retry only failed papers; retain other data")
    p.add_argument("--verify-boundaries", action="store_true",
                   help="Probe the two inferred cross-month endpoints BEFORE crawl")
    p.add_argument("--no-version-dates", action="store_true",
                   help="Skip optional intermediate revision-date lookups")
    p.add_argument("--preview", action="store_true", help="Count IDs and show batches without network")
    p.add_argument("--check-backups", action="store_true", help="Re-hash every existing checkpoint")
    p.add_argument("--quiet", action="store_true",
                   help="Do not print crawl progress, summaries, or retry warnings")
    return p


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 100 or args.next < 0:
        raise SystemExit("batch-size must be 1..100; --next must be nonnegative")
    if args.workers < 1 or args.retries < 0:
        raise SystemExit("--workers must be >= 1; --retries must be nonnegative")
    all_ids = assigned_ids(args.range_number)
    batches = build_batches(all_ids, args.batch_size)
    print(f"Assigned range={args.range_number or 'ALL'}: {len(all_ids)} unique IDs "
          f"({len(batches)} batches of up to {args.batch_size})", flush=True)
    print(f"Start={all_ids[0]}, end={all_ids[-1]} (ordering follows the screenshot)", flush=True)
    if args.preview:
        for item in RANGES:
            if args.range_number in (0, item.number):
                print(f"  Range {item.number}: {item.first} -> {item.last}: {len(range_ids(item))} IDs" +
                      (" (month-end INFERRED, verify!)" if item.cross_month_limit else ""))
        return 0
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    indices = range(args.batch_start or 0, len(batches))
    completed = 0
    errors = 0
    with ArxivHTTP(delay=args.delay, retries=args.retries) as http:
        if args.verify_boundaries:
            verify_boundaries(http)
        for batch_index in indices:
            name, paper_ids = batches[batch_index]
            previous = _existing_manifest(args.backup_dir, name, paper_ids,
                                          verify_checksum=args.check_backups)
            if args.retry_failed:
                # Recovery only touches existing, valid, failed checkpoints.
                # Never create new batches during recovery.
                if previous is None or not _has_error(previous):
                    continue
            else:
                # Retry checkpoints that never got metadata because discovery failed.
                if previous is not None and _is_discovery_failed_checkpoint(
                        args.backup_dir, name, previous):
                    print(f"[RETRY] {name}: previous discovery failed; retrying this batch",
                          flush=True)
                    previous = None
                # Fast Crawl skips other completed checkpoints.
                if previous is not None:
                    continue
            result = _run_batch(paper_ids, name, args.output_root, args.backup_dir, http,
                                args.check_backups, args.retry_failed,
                                not args.no_version_dates, workers=args.workers)
            completed += 1
            errors += result["failed"]
            if args.next and completed >= args.next:
                break
    print(f"FINISHED: {completed} new/retried batches; {errors} paper errors. "
          f"Stored at {args.backup_dir}", flush=True)
    if completed == 0:
        print("All selected batches have checkpoints. For errors, use --retry-failed.")
    return 0 if not errors else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.quiet:
        return _main(argv)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        previous_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            return _main(argv)
        finally:
            logging.disable(previous_disable)


if __name__ == "__main__":
    raise SystemExit(main())
