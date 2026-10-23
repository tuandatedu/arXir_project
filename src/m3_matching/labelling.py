"""
Ground truth: pair BibTeX entry ↔ crawled reference CÙNG publication.

Ràng buộc đề:
- Manual: ≥ 5 publications, mỗi paper ≥ 20 labeled entries, tổng ≥ 100
- Auto (regex / string similarity): ≥ 10% publications NGOÀI manual pool,
  và auto label MỌI BibTeX entry của paper được chọn
- 1 entry tối đa 1 true reference; không khớp → groundtruth = None (all-negative row)

Format nội bộ (ghi rõ README):
data/labels/{arxiv_id}.jsonl
  {"citation_key": "...", "groundtruth_arxiv_id": "2310.12345"|null, "source": "manual"|"auto"}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

LabelSource = Literal["manual", "auto"]


def auto_match_one(
    bib_entry: dict[str, Any],
    references: list[dict[str, Any]],
) -> str | None:
    """
    Heuristic matcher (regex / similarity). Trả ref_arxiv_id hoặc None.

    Cần code bên trong (gợi ý):
    - exact DOI
    - normalized title equality
    - rapidfuzz / Levenshtein title + author overlap, threshold ghi poster
    - chỉ so references của CÙNG arxiv_id citing
    """
    raise NotImplementedError("TODO(M3): auto_match_one")


def auto_label_publication(arxiv_id: str) -> list[dict[str, Any]]:
    """Label mọi BibTeX entry của 1 paper (bắt buộc nếu paper thuộc auto pool)."""
    raise NotImplementedError("TODO(M3): auto_label_publication")


def load_labels(labels_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Đọc data/labels → {arxiv_id: [label rows]}."""
    raise NotImplementedError("TODO(M3): load_labels")


def save_labels(arxiv_id: str, rows: list[dict[str, Any]], labels_dir: Path) -> Path:
    """Ghi jsonl 1 publication."""
    raise NotImplementedError("TODO(M3): save_labels")


def validate_label_quota(labels: dict[str, list[dict[str, Any]]], n_publications_total: int) -> None:
    """
    Raise nếu thiếu quota đề:
    - manual papers ≥ MIN_MANUAL_PUBLICATIONS
    - mỗi manual ≥ MIN_LABELED_ENTRIES_PER_MANUAL_PAPER
    - tổng labeled ≥ MIN_LABELED_ENTRIES_TOTAL
    - auto papers ≥ ceil(MIN_AUTO_LABEL_FRACTION * (total - n_manual))
    """
    raise NotImplementedError("TODO(M3): validate_label_quota")
