"""Shared performance ledger for M1 crawl, reference, and table phases."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import os
from pathlib import Path
import threading
import time
import uuid

import psutil


FIELDS = (
    "run_id", "phase", "batch", "started_at_utc", "finished_at_utc",
    "elapsed_seconds", "papers_requested", "papers_processed",
    "discovery_seconds", "average_cpu_percent", "peak_cpu_percent", "cpu_samples",
    "peak_rss_bytes", "average_rss_bytes", "rss_samples",
    "persistent_output_bytes", "sampled_peak_scratch_bytes", "status",
)
LEDGER_NAME = "performance_metrics.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def directory_size(path: Path) -> int:
    """Return bytes currently stored below a directory, ignoring partial files."""
    root = Path(path)
    if not root.is_dir():
        return 0
    total = 0
    for item in root.rglob("*"):
        try:
            if item.is_file() and not item.name.endswith(".partial"):
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _processes(root_pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(root_pid)
        return [root, *root.children(recursive=True)]
    except (psutil.Error, OSError):
        return []


def append_metric_row(data_dir: Path, row: dict) -> dict:
    """Atomically append a row, normalizing it to the shared CSV schema."""
    reports_dir = Path(data_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / LEDGER_NAME
    existing: list[dict[str, str]] = []
    if path.is_file():
        with path.open("r", newline="", encoding="utf-8") as stream:
            existing = list(csv.DictReader(stream))
    normalized = {key: row.get(key, "") for key in FIELDS}
    normalized["run_id"] = normalized["run_id"] or uuid.uuid4().hex
    temp = path.with_name(path.name + ".partial")
    with temp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerow(normalized)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    return normalized


@contextmanager
def track_phase(data_dir: Path, phase: str, *, batch: str = "all",
                papers_requested: int | None = None):
    """Measure wall time, process-tree CPU/RSS and current persistent output size.

    CPU/RSS are sampled once per second and cover this process plus descendants.
    The yielded dict accepts phase-specific values such as papers_processed.
    A measurement is recorded even when the phase raises.
    """
    data_dir = Path(data_dir)
    process = psutil.Process(os.getpid())
    root_pid = int(os.environ.get("M1_METRICS_ROOT_PID", os.getpid()))
    started_at = utc_now()
    started = time.perf_counter()
    rss_samples: list[int] = []
    cpu_samples: list[float] = []
    stop = threading.Event()
    extra: dict = {}
    previous_cpu: dict[int, float] = {}
    previous_sample_time: float | None = None

    def sample() -> None:
        nonlocal previous_sample_time
        while not stop.is_set():
            rss_total = 0
            cpu_total = 0.0
            found = False
            current_cpu: dict[int, float] = {}
            now = time.monotonic()
            for proc in _processes(root_pid):
                try:
                    rss_total += proc.memory_info().rss
                    cpu_times = proc.cpu_times()
                    used = cpu_times.user + cpu_times.system
                    current_cpu[proc.pid] = used
                    if proc.pid in previous_cpu and previous_sample_time is not None:
                        cpu_total += max(0.0, used - previous_cpu[proc.pid]) * 100.0 / max(
                            now - previous_sample_time, 1e-6
                        )
                    found = True
                except (psutil.Error, OSError):
                    continue
            if found:
                rss_samples.append(rss_total)
                if previous_sample_time is not None:
                    cpu_samples.append(cpu_total)
            previous_cpu.clear()
            previous_cpu.update(current_cpu)
            previous_sample_time = now
            stop.wait(1.0)

    sampler = threading.Thread(target=sample, name=f"m1-metrics-{phase}", daemon=True)
    sampler.start()
    status = "ok"
    try:
        yield extra
    except BaseException:
        status = "error"
        raise
    finally:
        stop.set()
        sampler.join(timeout=3)
        final_rss = 0
        for proc in _processes(root_pid):
            try:
                final_rss += proc.memory_info().rss
            except (psutil.Error, OSError):
                continue
        if final_rss:
            rss_samples.append(final_rss)
        elapsed = time.perf_counter() - started
        append_metric_row(data_dir, {
            "run_id": uuid.uuid4().hex,
            "phase": phase,
            "batch": batch,
            "started_at_utc": started_at,
            "finished_at_utc": utc_now(),
            "elapsed_seconds": f"{elapsed:.3f}",
            "papers_requested": extra.get(
                "papers_requested", papers_requested if papers_requested is not None else ""
            ),
            "papers_processed": extra.get("papers_processed", ""),
            "discovery_seconds": extra.get("discovery_seconds", ""),
            "average_cpu_percent": round(sum(cpu_samples) / len(cpu_samples), 2)
            if cpu_samples else 0,
            "peak_cpu_percent": round(max(cpu_samples, default=0), 2),
            "cpu_samples": len(cpu_samples),
            "peak_rss_bytes": max(rss_samples, default=0),
            "average_rss_bytes": round(sum(rss_samples) / len(rss_samples))
            if rss_samples else 0,
            "rss_samples": len(rss_samples),
            "persistent_output_bytes": directory_size(data_dir),
            "status": status,
        })
