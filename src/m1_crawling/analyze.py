"""
Thống kê corpus M1 cho Jupyter Book (figure/table generate lúc compile, không screenshot).

Đề yêu cầu tối thiểu:
- số paper crawl thành công, overall success rate
- average paper size bytes trước/sau khi bỏ figure (archive vs extracted tex/bib)
- average references / paper, success rate crawl reference metadata
- runtime: time / paper, average, total discovery time
- memory: peak RAM, average RAM, max disk, final output size
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def corpus_stats(working_dir: Path) -> dict[str, Any]:
    """
    Duyệt data/working, đếm paper/version/empty/tex-size/ref coverage.

    Cần code bên trong:
    - n_assigned, n_resolved, n_versions, n_empty_versions
    - bytes_archives (nếu còn log), bytes_extracted
    - n_s2_refs, n_s2_with_arxiv, avg_refs_per_paper
    """
    raise NotImplementedError("TODO(M1): corpus_stats")


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Ghi data/tables/metrics_m1.json để Jupyter Book đọc khi compile."""
    raise NotImplementedError("TODO(M1): write_metrics")
