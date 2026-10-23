"""
MRR@5 trên Test set (2 publications: 1 manual + 1 auto).

MRR@5 = (1/|Q|) * sum 1/rank_i
rank_i = vị trí GT trong top-5; không có trong top-5 → 0.
|Q| = số labeled BibTeX entries trên Test.
"""

from __future__ import annotations

from typing import Any, Optional


def reciprocal_rank(groundtruth: Optional[str], candidates: list[Optional[str]], k: int = 5) -> float:
    """1/rank nếu GT nằm trong candidates[:k], else 0. GT None → 0 (all-negative)."""
    raise NotImplementedError("TODO(M3): reciprocal_rank")


def mrr_at_k(
    rows: list[dict[str, Any]],
    k: int = 5,
) -> float:
    """
    rows: prediction dicts có groundtruth_arxiv_id + cand_1..cand_5.

    Cần code bên trong: trung bình reciprocal_rank trên |Q| = len(rows).
    """
    raise NotImplementedError("TODO(M3): mrr_at_k")


def evaluate_split(partition: str, prediction_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Tính MRR@5 (+ có thể hit@1, hit@5) cho một partition; ghi metrics_m3.json."""
    raise NotImplementedError("TODO(M3): evaluate_split")
