"""Runtime, RAM, and directory-size measurements for reportable runs."""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time
from pathlib import Path
from typing import Any, Iterator


def sample_rss_bytes() -> int:
    """Return this process's resident memory in bytes."""
    # Import lazily so users who only need other helpers do not need psutil immediately.
    import psutil
    return int(psutil.Process().memory_info().rss)


@contextmanager
def track_run(name: str) -> Iterator[dict[str, Any]]:
    """Measure wall time and sampled RSS while the caller's work is running."""
    import psutil

    # Keep one process handle for repeated memory samples.
    process = psutil.Process()
    interval = 0.25
    samples = [int(process.memory_info().rss)]
    stop = threading.Event()

    # A background thread samples RAM while the caller does its work.
    def sample_loop() -> None:
        while not stop.wait(interval):
            try:
                samples.append(int(process.memory_info().rss))
            except psutil.Error:
                break

    # perf_counter is monotonic and suited to measuring elapsed durations.
    started = time.perf_counter()
    sampler = threading.Thread(target=sample_loop, name=f"rss-{name}", daemon=True)
    sampler.start()
    metrics: dict[str, Any] = {"name": name}
    try:
        # Let the caller attach its own counters while the measured work runs.
        yield metrics
    finally:
        samples.append(int(process.memory_info().rss))
        stop.set()
        sampler.join()
        # Publish the total duration and summary of all RSS samples to the caller.
        metrics.update({
            "duration_sec": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": max(samples),
            "avg_rss_bytes": round(sum(samples) / len(samples)),
            "rss_sample_count": len(samples),
        })


def directory_size_bytes(path: str | Path) -> int:
    """Sum file sizes under a directory, skipping inaccessible files safely."""
    path = Path(path)
    # Handle a single file directly; absent paths have no stored bytes.
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    total = 0
    # Recursively add regular files and ignore symlinks to avoid double counting.
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total
