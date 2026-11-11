"""Batch Semantic Scholar references crawler shared by the Colab notebook.

The notebook must not re-implement the request loop: pacing, cooldown, payload
validation and cache handling all live in ``semantic_scholar.py``. This module
only orchestrates one publication at a time (sequential), so every HTTP attempt
(including retries inside ``request_with_retry``) still goes through the shared
rate limiter.

Status contract per publication:
- ``ok``: HTTP 200 + payload object + ``references`` is a list (empty is ok).
- ``not_indexed``: only HTTP 404 (S2 has not indexed the paper yet).
- ``failed``: HTTP/network error, invalid JSON, missing/wrong ``references``
  field, or a reference item that is not an object.
- ``invalid_id``: local arXiv ID cannot be normalized; no request is made.

A cache file is written only for ``ok`` results. Missing/wrong payload
structures never create a successful-looking empty cache. A cache file that is
not a JSON list of objects is treated as broken and recrawled.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional

from src.common.ids import folder_name_for_arxiv_id, normalize_arxiv_id
from src.m1_crawling.semantic_scholar import (
    extract_reference_objects,
    fetch_s2_payload_with_status,
    s2_ref_to_local_record,
)

LOG = logging.getLogger(__name__)

_API_ERROR_KINDS = ("network", "request_rejected")
_PROCESSING_ERROR_KINDS = frozenset(
    {"invalid_json", "invalid_payload", "processing"})


def cache_path_for(refs_root: Path | str, arxiv_id: str) -> Path:
    """Return the flat cache path for one publication, e.g. ``2310-00001.json``."""
    return Path(refs_root) / f"{folder_name_for_arxiv_id(arxiv_id)}.json"


def read_cached_records(path: Path | str) -> list[dict[str, Any]]:
    """Read a cache file, rejecting anything that is not a list of objects."""
    with Path(path).open("r", encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError("cache must be a JSON list")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"cache item {index} is not an object")
    return records


def find_empty_cache_ids(
    papers_meta: list[dict[str, Any]],
    refs_root: Path | str,
) -> list[str]:
    """List normalized IDs whose existing cache is a valid but empty list.

    An empty cache can be legitimate (the publication has zero references) or
    can be left over from older code that turned a missing ``references``
    field into ``[]``. Review the list, then pass only the IDs that must be
    re-queried to ``run_s2_batch(..., force_recrawl_ids=...)``. All other cache
    files stay untouched.
    """
    refs_root = Path(refs_root)
    empty_ids: list[str] = []
    for paper in papers_meta:
        raw_id = paper.get("arxiv_id", "") if isinstance(paper, dict) else ""
        try:
            base_id = normalize_arxiv_id(raw_id)
        except (ValueError, TypeError):
            continue
        path = cache_path_for(refs_root, base_id)
        if not path.exists():
            continue
        try:
            records = read_cached_records(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not records:
            empty_ids.append(base_id)
    return empty_ids


def _write_cached_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Write the cache atomically so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_file, path)


def _record_from_cache(arxiv_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    n_refs = len(records)
    n_arxiv = sum(1 for record in records if record.get("ref_arxiv_id") is not None)
    return {
        "arxiv_id": arxiv_id,
        "status": "ok",
        "n_refs": n_refs,
        "n_arxiv": n_arxiv,
        "n_refs_without_arxiv": n_refs - n_arxiv,
        "is_zero_ref": n_refs == 0,
        "is_api_error": False,
        "is_invalid_id": False,
        "from_cache": True,
        "elapsed_s": "",
        "n_invalid_refs": 0,
        "error_kind": "",
        "error": "",
    }


def _invalid_id_record(raw_id: Any) -> dict[str, Any]:
    return {
        "arxiv_id": raw_id or "INVALID",
        "status": "invalid_id",
        "n_refs": 0,
        "n_arxiv": 0,
        "n_refs_without_arxiv": 0,
        "is_zero_ref": False,
        "is_api_error": False,
        "is_invalid_id": True,
        "from_cache": False,
        "elapsed_s": "",
        "n_invalid_refs": 0,
        "error_kind": "invalid_id",
        "error": "arXiv ID không hợp lệ hoặc bị thiếu",
    }


def _fetch_and_cache(
    base_id: str,
    refs_file: Path,
    api_key: Optional[str],
) -> dict[str, Any]:
    """Fetch one publication, validate the payload and optionally write cache."""
    started = time.perf_counter()
    payload, status, error_msg, error_kind = fetch_s2_payload_with_status(
        base_id, api_key)
    elapsed = time.perf_counter() - started

    local_records: list[dict[str, Any]] = []
    n_invalid_refs = 0

    if status == "ok" and payload is not None:
        try:
            raw_refs, invalid_refs = extract_reference_objects(payload)
            n_invalid_refs = len(invalid_refs)
            if invalid_refs:
                status = "failed"
                error_kind = "invalid_payload"
                error_msg = (
                    "Invalid reference item structure: "
                    f"{n_invalid_refs} non-object item(s)"
                )
                LOG.warning(
                    "Semantic Scholar returned %d non-object reference(s) for "
                    "%s; not caching (first: %r)",
                    n_invalid_refs, base_id, invalid_refs[0])
            else:
                local_records = [
                    s2_ref_to_local_record(base_id, item) for item in raw_refs
                ]
        except Exception as exc:  # local processing failure
            status = "failed"
            error_kind = "processing"
            error_msg = f"Reference processing error: {exc}"
            local_records = []
            n_invalid_refs = 0

    if status == "ok":
        try:
            _write_cached_records(refs_file, local_records)
        except Exception as exc:  # cache write failure must not look like ok
            status = "failed"
            error_kind = "processing"
            error_msg = f"Cache write error: {exc}"
            local_records = []
            n_invalid_refs = 0

    n_refs = len(local_records)
    n_arxiv = sum(
        1 for record in local_records if record.get("ref_arxiv_id") is not None)
    return {
        "arxiv_id": base_id,
        "status": status,
        "n_refs": n_refs,
        "n_arxiv": n_arxiv,
        "n_refs_without_arxiv": n_refs - n_arxiv,
        "is_zero_ref": status == "ok" and n_refs == 0,
        "is_api_error": (
            status == "failed"
            and (error_kind.startswith("http_") or error_kind in _API_ERROR_KINDS)
        ),
        "is_invalid_id": False,
        "from_cache": False,
        "elapsed_s": elapsed,
        "n_invalid_refs": n_invalid_refs,
        "error_kind": error_kind or "",
        "error": error_msg or "",
    }


def run_s2_batch(
    papers_meta: list[dict[str, Any]],
    refs_root: Path | str,
    api_key: Optional[str] = None,
    progress_every: int = 50,
    progress: Optional[Callable[[int, int, dict[str, Any]], None]] = None,
    force_recrawl_ids: Optional[list[str]] = None,
) -> tuple[list[dict[str, Any]], int]:
    """Crawl references for every publication, resuming from the local cache.

    ``force_recrawl_ids`` skips the cache for the listed publications only
    (used after reviewing empty caches left by older code). Returns
    ``(results, n_invalid_ids)`` where each result describes one input
    publication (including cache hits, ``not_indexed`` and ``invalid_id``).
    """
    refs_root = Path(refs_root)
    refs_root.mkdir(parents=True, exist_ok=True)
    total = len(papers_meta)
    results: list[dict[str, Any]] = []
    n_invalid_ids = 0
    force_recrawl: set[str] = set()
    for raw_id in force_recrawl_ids or []:
        try:
            force_recrawl.add(normalize_arxiv_id(raw_id))
        except (ValueError, TypeError):
            continue

    for index, paper in enumerate(papers_meta, start=1):
        raw_id = paper.get("arxiv_id", "") if isinstance(paper, dict) else ""
        try:
            base_id = normalize_arxiv_id(raw_id)
        except (ValueError, TypeError):
            n_invalid_ids += 1
            result = _invalid_id_record(raw_id)
        else:
            refs_file = cache_path_for(refs_root, base_id)
            if refs_file.exists() and base_id not in force_recrawl:
                try:
                    records = read_cached_records(refs_file)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    LOG.warning(
                        "S2 cache invalid for %s; recrawling: %s", base_id, exc)
                else:
                    result = _record_from_cache(base_id, records)
                    results.append(result)
                    if progress is not None and (
                            index % progress_every == 0 or index == total):
                        progress(index, total, result)
                    continue
            result = _fetch_and_cache(base_id, refs_file, api_key)

        results.append(result)
        if progress is not None and (
                index % progress_every == 0 or index == total):
            progress(index, total, result)

    return results, n_invalid_ids


def summarize_s2_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-publication results into report metrics.

    ``n_ok`` includes cache hits; ``n_attempted_fresh`` is the denominator for
    success/fresh timing. ``elapsed_s`` covers one publication API wait
    (including pacing and retries) and excludes normalization/cache writes.
    """
    n_input = len(results)
    ok_rows = [row for row in results if row.get("status") == "ok"]
    fresh_rows = [
        row for row in results
        if not row.get("from_cache", False) and not row.get("is_invalid_id", False)
    ]
    fresh_ok_rows = [row for row in fresh_rows if row.get("status") == "ok"]
    cached_ok_rows = [
        row for row in results
        if row.get("status") == "ok" and row.get("from_cache", False)
    ]

    n_refs_total = sum(int(row.get("n_refs", 0) or 0) for row in ok_rows)
    n_refs_with_arxiv = sum(int(row.get("n_arxiv", 0) or 0) for row in ok_rows)
    n_refs_without_arxiv = sum(
        int(row.get("n_refs_without_arxiv", 0) or 0) for row in ok_rows)

    elapsed_values = [
        float(row["elapsed_s"]) for row in fresh_rows
        if isinstance(row.get("elapsed_s"), (int, float))
        and not isinstance(row.get("elapsed_s"), bool)
    ]
    total_fetch_elapsed = sum(elapsed_values)

    n_api_errors = sum(
        1 for row in results
        if row.get("status") == "failed"
        and (
            str(row.get("error_kind", "")).startswith("http_")
            or row.get("error_kind") in _API_ERROR_KINDS
        )
    )
    n_processing_errors = sum(
        1 for row in results
        if row.get("status") == "failed"
        and row.get("error_kind") in _PROCESSING_ERROR_KINDS
    )

    n_attempted_fresh = len(fresh_rows)
    return {
        "n_input": n_input,
        "n_ok": len(ok_rows),
        "n_ok_fresh": len(fresh_ok_rows),
        "n_ok_from_cache": len(cached_ok_rows),
        "n_cache_hits": sum(1 for row in results if row.get("from_cache", False)),
        "n_attempted_fresh": n_attempted_fresh,
        "n_not_indexed": sum(
            1 for row in results if row.get("status") == "not_indexed"),
        "n_failed": sum(1 for row in results if row.get("status") == "failed"),
        "n_invalid_ids": sum(
            1 for row in results if row.get("status") == "invalid_id"),
        "n_zero_refs": sum(1 for row in ok_rows if row.get("is_zero_ref")),
        "n_api_errors": n_api_errors,
        "n_processing_errors": n_processing_errors,
        "n_refs_total": n_refs_total,
        "n_refs_with_arxiv": n_refs_with_arxiv,
        "n_refs_without_arxiv": n_refs_without_arxiv,
        "success_rate_all_input": (
            len(ok_rows) / n_input if n_input else 0.0),
        "success_rate_fresh": (
            len(fresh_ok_rows) / n_attempted_fresh
            if n_attempted_fresh else 0.0),
        "avg_s2_seconds_per_publication_fetch": (
            total_fetch_elapsed / len(elapsed_values)
            if elapsed_values else 0.0),
        "avg_fetch_sample_count": len(elapsed_values),
        "total_fetch_elapsed_sec": total_fetch_elapsed,
        "status_counts": dict(Counter(
            str(row.get("status", "")) for row in results)),
    }
