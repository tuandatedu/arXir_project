"""Small, durable wall-clock runtime ledger for the Colab arXiv crawler.

Each notebook invocation records exactly one event AFTER subprocess.run returns.
Exporting a report only READS this ledger and never appends new entries.
Older runs that predate this module are intentionally not fabricated.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

HISTORY_FILENAME = "runtime_history.csv"
HISTORY_FIELDS = [
    "run_id", "started_at_utc", "finished_at_utc", "mode", "range_id",
    "batch_size", "batches_requested", "elapsed_seconds", "exit_code",
    "result", "checkpoint_count_before", "checkpoint_count_after",
    "new_checkpoints", "updated_checkpoints",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def checkpoint_state(backup_dir: Path) -> dict[str, tuple[int, int]]:
    """Lightweight snapshot of completion markers (no archive reads)."""
    result = {}
    for path in Path(backup_dir).glob("batch_*.json"):
        stat = path.stat()
        result[path.name] = (stat.st_size, stat.st_mtime_ns)
    return result


def read_runtime_history(backup_dir: Path) -> list[dict]:
    path = Path(backup_dir) / HISTORY_FILENAME
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or not set(HISTORY_FIELDS).issubset(reader.fieldnames):
            raise ValueError(f"Runtime ledger has missing columns: {path}")
        records = list(reader)
    seen = set()
    for row in records:
        run_id = row["run_id"]
        if not run_id or run_id in seen:
            raise ValueError(f"Duplicate/empty runtime run_id in {path}")
        seen.add(run_id)
        if row["mode"] not in ("fast", "recovery"):
            raise ValueError(f"Unexpected runtime mode: {row['mode']}")
        seconds = float(row["elapsed_seconds"])
        if not 0 <= seconds < 10**9:
            raise ValueError("Invalid elapsed_seconds")
    return records


def record_runtime(backup_dir: Path, *, mode: str, range_id: int,
                   batch_size: int, batches_requested: int, elapsed_seconds: float,
                   exit_code: int, started_at_utc: str,
                   before: dict[str, tuple[int, int]],
                   after: dict[str, tuple[int, int]]) -> dict:
    """Append a single run event using an atomic replace, not in-place writes.

    Do not run multiple Colab notebooks concurrently against the same backup dir.
    """
    if mode not in ("fast", "recovery"):
        raise ValueError("mode must be fast or recovery")
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be nonnegative")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    rows = read_runtime_history(backup_dir)
    row = {
        "run_id": uuid.uuid4().hex,
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now(),
        "mode": mode,
        "range_id": range_id,
        "batch_size": batch_size,
        "batches_requested": batches_requested,
        "elapsed_seconds": f"{elapsed_seconds:.3f}",
        "exit_code": exit_code,
        "result": "complete" if exit_code == 0 else "partial" if exit_code == 2 else "failed",
        "checkpoint_count_before": len(before),
        "checkpoint_count_after": len(after),
        "new_checkpoints": len(after.keys() - before.keys()),
        "updated_checkpoints": sum(name in before and before[name] != state
                                   for name, state in after.items()),
    }
    rows.append(row)
    path = backup_dir / HISTORY_FILENAME
    temp = path.with_name(path.name + ".partial")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return row


def summarize_runtime(rows: list[dict], total_records: int) -> dict:
    fast = sum(float(r["elapsed_seconds"]) for r in rows if r["mode"] == "fast")
    recovery = sum(float(r["elapsed_seconds"]) for r in rows if r["mode"] == "recovery")
    total = fast + recovery
    return {
        "fast_crawl_seconds": round(fast, 3),
        "recovery_seconds": round(recovery, 3),
        "total_runtime_seconds": round(total, 3),
        "fast_crawl_runs": sum(r["mode"] == "fast" for r in rows),
        "recovery_attempts": sum(r["mode"] == "recovery" for r in rows),
        "runtime_recorded_runs": len(rows),
        "average_seconds_per_id": round(total / total_records, 3) if total_records else None,
        "runtime_note": (
            "Wall-clock time recorded by Colab from this patch onward, including failed "
            "runs that returned an exit code. Earlier runs and sessions forcibly terminated "
            "before writing a ledger row are not included. Re-exporting does not add time."
        ),
    }
