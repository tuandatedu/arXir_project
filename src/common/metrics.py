"""
Đo runtime + memory footprint (dùng cho report M1/M2, Colab CPU-only).

Đề gợi ý: peak RAM qua psutil hoặc /usr/bin/time -v, average RAM sampling,
disk qua du. Wall-clock end-to-end cho cả hệ thống.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from typing import Any, Iterator

from src.common.config import TABLES_DIR

_SAMPLE_INTERVAL_SEC = 0.5


@contextmanager
def track_run(name: str) -> Iterator[dict[str, Any]]:
    """
    Context manager bọc một giai đoạn pipeline, ghi wall time + peak/avg RAM.

    - Bắt đầu: time.perf_counter(), psutil.Process(), thread/sample RAM định kỳ.
    - yield dict metrics (caller có thể nhét thêm key).
    - Kết thúc: ghi duration_sec, peak_rss_bytes, avg_rss_bytes.
    - Ghi ra data/tables/metrics_{name}.json.
    """
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                       for char in name.lower()):
        raise ValueError("name must be a non-empty snake_case identifier")
    payload: dict[str, Any] = {"name": name}
    samples: list[int] = []
    stop = threading.Event()
    process = None
    try:
        import psutil
        process = psutil.Process()
        samples.append(process.memory_info().rss)
    except Exception:  # psutil optional — Colab always has it, local runs may not.
        process = None

    def _sample() -> None:
        while not stop.wait(_SAMPLE_INTERVAL_SEC):
            if process is not None:
                try:
                    samples.append(process.memory_info().rss)
                except Exception:
                    return

    sampler = threading.Thread(target=_sample, daemon=True)
    start = time.perf_counter()
    if process is not None:
        sampler.start()
    try:
        yield payload
    finally:
        stop.set()
        if process is not None:
            sampler.join(timeout=_SAMPLE_INTERVAL_SEC + 1.0)
        payload["duration_sec"] = round(time.perf_counter() - start, 3)
        if samples:
            payload["peak_rss_bytes"] = max(samples)
            payload["avg_rss_bytes"] = round(sum(samples) / len(samples))
        else:
            payload["peak_rss_bytes"] = None
            payload["avg_rss_bytes"] = None
        out = Path(TABLES_DIR) / f"metrics_{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def directory_size_bytes(path: str) -> int:
    """Tổng kích thước thư mục (tương đương `du -sb`)."""
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        return root.stat().st_size
    return sum(item.stat().st_size for item in root.rglob("*") if item.is_file())


def sample_rss_bytes() -> int:
    """RSS hiện tại của process (psutil.Process().memory_info().rss)."""
    import psutil
    return psutil.Process().memory_info().rss
