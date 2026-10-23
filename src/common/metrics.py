"""
Đo runtime + memory footprint (dùng cho report M1/M2, Colab CPU-only).

Đề gợi ý: peak RAM qua psutil hoặc /usr/bin/time -v, average RAM sampling,
disk qua du. Wall-clock end-to-end cho cả hệ thống.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def track_run(name: str) -> Iterator[dict[str, Any]]:
    """
    Context manager bọc một giai đoạn pipeline, ghi wall time + peak/avg RAM.

    Cần code bên trong:
    - Bắt đầu: time.perf_counter(), psutil.Process(), thread/sample RAM định kỳ.
    - yield dict metrics (caller có thể nhét thêm key).
    - Kết thúc: ghi duration_sec, peak_rss_bytes, avg_rss_bytes.
    - Có thể ghi ra data/tables/metrics_{name}.json.
    """
    raise NotImplementedError("TODO(common): track_run")
    yield {}  # noqa: unreachable — giữ chữ ký generator cho teammate


def directory_size_bytes(path: str) -> int:
    """Tổng kích thước thư mục (tương đương `du -sb`)."""
    raise NotImplementedError("TODO(common): directory_size_bytes")


def sample_rss_bytes() -> int:
    """RSS hiện tại của process (psutil.Process().memory_info().rss)."""
    raise NotImplementedError("TODO(common): sample_rss_bytes")
