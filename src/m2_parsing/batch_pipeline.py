"""Bounded-memory M2 processing for M1 checkpoint archives."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from collections.abc import Mapping
from pathlib import Path

from src.common.ids import normalize_arxiv_id
from src.common.io import write_json

from .archive_input import restore_batch
from .pipeline import run_milestone2

LOG = logging.getLogger(__name__)
PIPELINE_REVISION = 4


def discover_checkpoint_batches(batch_dir: Path | Mapping[str, Path]) -> list[tuple[str, Path, dict]]:
    """Validate manifests and IDs before modifying any output; scope repeated batch names."""
    directories = {"": Path(batch_dir)} if not isinstance(batch_dir, Mapping) else batch_dir
    if not directories:
        raise ValueError("No checkpoint directories selected")
    batches = []
    seen_ids: set[str] = set()
    for scope, directory in sorted(directories.items()):
        if scope and (scope in (".", "..") or any(char in scope for char in "/\\:")):
            raise ValueError(f"Invalid checkpoint namespace: {scope!r}")
        archives = sorted(Path(directory).glob("batch_*.tar.gz"))
        if not archives:
            raise FileNotFoundError(f"No batch_*.tar.gz in {directory}. Copy source checkpoints here first.")
        for archive in archives:
            manifest_path = archive.with_suffix("").with_suffix(".json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(manifest, dict):
                raise ValueError(f"Expected a manifest object: {manifest_path}")
            raw_ids = manifest.get("ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ValueError(f"Missing or empty ids list: {manifest_path}")
            ids = [normalize_arxiv_id(value) for value in raw_ids]
            if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
                raise ValueError(f"Overlapping IDs in {archive}")
            if not isinstance(manifest.get("archive_sha256"), str) or not isinstance(manifest.get("archive_bytes"), int):
                raise ValueError(f"Missing checkpoint checksum/size: {manifest_path}")
            seen_ids.update(ids)
            batches.append((scope, archive, manifest))
    return batches


def _process_batch(args: tuple[str, Path, Path, Path, bool]) -> tuple[str, int, dict, bool]:
    scope, archive, working_dir, tables_dir, resume = args
    manifest = json.loads(archive.with_suffix("").with_suffix(".json").read_text(encoding="utf-8-sig"))
    archive_key = (Path(scope) / archive.name).as_posix()
    part_dir = tables_dir / "batches" / archive_key.removesuffix(".tar.gz")
    marker = part_dir / "complete.json"
    if resume and marker.is_file():
        completed = json.loads(marker.read_text(encoding="utf-8"))
        outputs = ("elements.jsonl", "hierarchy.jsonl", "bibtex.jsonl", "metrics_m2.json")
        if (completed.get("pipeline_revision") == PIPELINE_REVISION
                and completed.get("archive_sha256") == manifest["archive_sha256"]
                and all((part_dir / name).is_file() for name in outputs)):
            metrics = json.loads((part_dir / "metrics_m2.json").read_text(encoding="utf-8"))
            if metrics.get("n_publications") == len(manifest["ids"]):
                return archive_key, 0, metrics, True
    marker.unlink(missing_ok=True)
    restored = restore_batch(archive, working_dir)
    run_milestone2(working_dir=working_dir, arxiv_ids=manifest["ids"], tables_dir=part_dir)
    metrics = json.loads((part_dir / "metrics_m2.json").read_text(encoding="utf-8"))
    write_json(marker, {"archive_sha256": manifest["archive_sha256"],
                        "pipeline_revision": PIPELINE_REVISION})
    return archive_key, restored, metrics, False


def run_checkpoint_batches(batch_dir: Path | Mapping[str, Path], working_dir: Path, tables_dir: Path,
                           workers: int = 1, resume: bool = False) -> dict:
    """Process batches from one directory or named ranges, concatenating final tables."""
    working_dir, tables_dir = map(Path, (working_dir, tables_dir))
    if workers < 1:
        raise ValueError("workers must be >= 1")
    batches = discover_checkpoint_batches(batch_dir)
    tables_dir.mkdir(parents=True, exist_ok=True)
    names = ("elements", "hierarchy", "bibtex")
    for name in names:
        (tables_dir / f"{name}.jsonl").write_text("", encoding="utf-8")
    start = time.perf_counter()
    batch_metrics: list[dict] = []
    reused_batches = 0
    total_rss_samples: list[int] = []
    stop_sampling = threading.Event()
    try:
        import psutil
        parent_process = psutil.Process()
    except ImportError:
        parent_process = None

    def sample_total_rss() -> None:
        while not stop_sampling.wait(0.1):
            try:
                processes = [parent_process, *parent_process.children(recursive=True)]
                total_rss_samples.append(sum(proc.memory_info().rss for proc in processes if proc.is_running()))
            except Exception:
                continue

    sampler = threading.Thread(target=sample_total_rss, daemon=True)
    if parent_process is not None:
        sampler.start()
    jobs = ((scope, archive, working_dir, tables_dir, resume) for scope, archive, _ in batches)
    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        results = executor.map(_process_batch, jobs) if executor else map(_process_batch, jobs)
        for number, (archive_name, restored, metrics, reused) in enumerate(results, 1):
            part_dir = tables_dir / "batches" / archive_name.removesuffix(".tar.gz")
            reused_batches += int(reused)
            batch_metrics.append(metrics)
            for name in names:
                with (part_dir / f"{name}.jsonl").open("r", encoding="utf-8") as source:
                    with (tables_dir / f"{name}.jsonl").open("a", encoding="utf-8") as target:
                        for line in source:
                            target.write(line)
            LOG.info("M2 batch %d/%d: %s, %d files, %d elements, %.1f sec",
                     number, len(batches), archive_name, restored,
                     metrics["n_elements_after_dedup"], metrics["duration_sec"])
    finally:
        if executor:
            executor.shutdown(wait=True)
        stop_sampling.set()
        if parent_process is not None:
            sampler.join(timeout=0.2)

    summed = ("n_publications", "n_versions_total", "n_versions_parsed", "n_versions_empty", "n_versions_failed", "n_versions_partial",
              "n_elements_before_dedup", "n_elements_after_dedup", "n_bib_before", "n_bib_after",
              "n_hierarchy_edges", "output_bytes")
    result = {key: sum(item[key] for item in batch_metrics) for key in summed}
    result["coverage"] = [row for item in batch_metrics for row in item["coverage"]]
    result["duration_sec"] = round(sum(item["duration_sec"] for item in batch_metrics), 3)
    result["avg_publication_sec"] = round(result["duration_sec"] / result["n_publications"], 3)
    result["peak_worker_rss_bytes"] = max((item["peak_rss_bytes"] or 0) for item in batch_metrics)
    result["peak_rss_bytes"] = max(total_rss_samples) if total_rss_samples else result["peak_worker_rss_bytes"]
    result["version_success_rate"] = (result["n_versions_parsed"] / result["n_versions_total"]
                                      if result["n_versions_total"] else 0.0)
    result["normalized"] = True
    result["batch_count"] = len(batches)
    result["reused_batches"] = reused_batches
    result["pipeline_revision"] = PIPELINE_REVISION
    result["end_to_end_sec"] = round(time.perf_counter() - start, 3)
    write_json(tables_dir / "metrics_m2.json", result)
    return result
