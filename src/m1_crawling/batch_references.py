"""Fetch Semantic Scholar references for every completed batch checkpoint.

For each ``batch_XXXXX.json`` / ``batch_XXXXX.tar.gz`` pair in ``data_dir`` this module
writes one file per paper to ``reference_XXXXX/{2603-15580}.json`` and merges a summary
into the batch manifest under the key ``references``. The manifest's ``ids``,
``archive_bytes`` and ``archive_sha256`` are never changed.

A reference file looks like::

    {"arxiv_id": "2603.15580", "status": "ok|empty|error", "error": null,
     "fetched_at_utc": "...", "references": [<local record>, ...]}

``references`` keeps EVERY reference S2 returned (also those without an arXiv ID);
build_tables.py later keeps only the ones with an arXiv ID for the published table.
Status meaning: ``ok`` = at least one reference, ``empty`` = S2 returned none (paper not
indexed yet or no references), ``error`` = request failed after retries (retried on re-run).
Re-running is safe: papers with an ``ok`` file are not requested again.
"""
from __future__ import annotations

import json
import logging
import tarfile
from pathlib import Path
from typing import Iterable, Optional

from src.common.ids import folder_name_for_arxiv_id
from .runtime_tracking import utc_now
from .semantic_scholar import fetch_s2_references, s2_ref_to_local_record

LOG = logging.getLogger(__name__)


def _write_json_atomic(path: Path, payload: object) -> None:
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def reference_dir_for(data_dir: Path, batch_name: str) -> Path:
    """batch_00000 -> data_dir/reference_00000"""
    return Path(data_dir) / ("reference_" + batch_name.split("_", 1)[1])


def _crawl_statuses(archive: Path) -> dict[str, str]:
    """{arxiv_id: status} from crawl_records.jsonl, stopping as soon as it is found."""
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            if member.name == "crawl_records.jsonl":
                handle = tf.extractfile(member)
                rows = [json.loads(line) for line in handle if line.strip()] if handle else []
                return {row["arxiv_id"]: row.get("status") for row in rows}
    raise ValueError(f"crawl_records.jsonl missing in {archive}")


def fetch_one(arxiv_id: str, api_key: Optional[str] = None) -> dict:
    """Request one paper's references; never raises (errors become status 'error')."""
    record = {"arxiv_id": arxiv_id, "status": "ok", "error": None,
              "fetched_at_utc": utc_now(), "references": []}
    try:
        raw = fetch_s2_references(arxiv_id, api_key=api_key)
        record["references"] = [s2_ref_to_local_record(arxiv_id, ref) for ref in raw]
        if not record["references"]:
            record["status"] = "empty"
    except Exception as exc:  # network loss, 429 after retries, 5xx, malformed payload
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        LOG.warning("Semantic Scholar failed for %s: %s", arxiv_id, record["error"])
    return record


def paper_summary(record: dict) -> dict:
    refs = record.get("references") or []
    return {"status": record.get("status"), "n_refs": len(refs),
            "n_with_arxiv_id": sum(bool(r.get("ref_arxiv_id")) for r in refs)}


def crawl_references(data_dir: Path, *, batch_names: Optional[Iterable[str]] = None,
                     retry_empty: bool = False, api_key: Optional[str] = None) -> list[str]:
    """Fetch missing references for valid checkpoints. Returns the batches it processed."""
    data_dir = Path(data_dir)
    wanted = set(batch_names) if batch_names is not None else None
    processed: list[str] = []
    for marker in sorted(data_dir.glob("batch_*.json")):
        name = marker.stem
        if wanted is not None and name not in wanted:
            continue
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        archive = marker.with_suffix(".tar.gz")
        if not archive.is_file() or archive.stat().st_size != manifest.get("archive_bytes"):
            print(f"[SKIP] {name}: checkpoint chưa hợp lệ, bỏ qua reference", flush=True)
            continue
        done = manifest.get("references")
        out_dir = reference_dir_for(data_dir, name)
        if (done and done.get("papers_error", 1) == 0
                and (not retry_empty or done.get("papers_empty", 0) == 0)
                and out_dir.is_dir()):
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        crawl_status = _crawl_statuses(archive)
        ids = manifest["ids"]
        per_paper: dict[str, dict] = {}
        print(f"\n[REFERENCE] {name}: {len(ids)} paper -> {out_dir.name}/", flush=True)

        for i, arxiv_id in enumerate(ids, 1):
            if crawl_status.get(arxiv_id) == "not_found":
                per_paper[arxiv_id] = {"status": "skipped", "n_refs": 0, "n_with_arxiv_id": 0}
                continue
            path = out_dir / f"{folder_name_for_arxiv_id(arxiv_id)}.json"
            record = None
            if path.is_file():
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    record = None  # corrupt/partial file: fetch again
            if record is not None and (record.get("status") == "error"
                                       or (retry_empty and record.get("status") == "empty")):
                record = None
            if record is None:
                record = fetch_one(arxiv_id, api_key)
                _write_json_atomic(path, record)
                info = paper_summary(record)
                print(f"  [{i}/{len(ids)}] {arxiv_id}: {record['status']} "
                      f"({info['n_refs']} ref, {info['n_with_arxiv_id']} có arXiv ID)"
                      + (f" - {record['error']}" if record["error"] else ""), flush=True)
            per_paper[arxiv_id] = paper_summary(record)

        statuses = [p["status"] for p in per_paper.values()]
        summary = {
            "dir": out_dir.name, "updated_at_utc": utc_now(),
            "papers_ok": statuses.count("ok"), "papers_empty": statuses.count("empty"),
            "papers_error": statuses.count("error"), "papers_skipped": statuses.count("skipped"),
            "total_refs": sum(p["n_refs"] for p in per_paper.values()),
            "refs_with_arxiv_id": sum(p["n_with_arxiv_id"] for p in per_paper.values()),
            "per_paper": per_paper,
        }
        # Re-read right before writing; identity fields must stay untouched.
        fresh = json.loads(marker.read_text(encoding="utf-8"))
        if fresh.get("ids") != manifest["ids"] or fresh.get("archive_bytes") != manifest.get("archive_bytes"):
            raise RuntimeError(f"{marker.name} changed while fetching references; run again")
        fresh["references"] = summary
        _write_json_atomic(marker, fresh)
        print(f"[REFERENCE] {name}: ok={summary['papers_ok']} empty={summary['papers_empty']} "
              f"error={summary['papers_error']} skipped={summary['papers_skipped']} | "
              f"{summary['total_refs']} ref, {summary['refs_with_arxiv_id']} có arXiv ID", flush=True)
        processed.append(name)
    return processed
