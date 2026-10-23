"""
Feature engineering cho cặp (bibtex entry, crawled reference) hoặc list ứng viên.

Đề cho phép dùng hierarchy M2 (ví dụ: section chứa \\cite{key}).
Mỗi feature phải giải thích Ý TƯỞNG trong README + poster.
"""

from __future__ import annotations

from typing import Any


def title_similarity(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """Score 0..1 (Levenshtein / Jaccard / cosine TF-IDF)."""
    raise NotImplementedError("TODO(M3): title_similarity")


def author_overlap(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """Jaccard / last-name overlap."""
    raise NotImplementedError("TODO(M3): author_overlap")


def year_distance(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """|year_bib - year_ref|; missing → sentinel (ghi rõ)."""
    raise NotImplementedError("TODO(M3): year_distance")


def cite_context_features(arxiv_id: str, citation_key: str) -> dict[str, float]:
    """
    Feature từ hierarchy M2 (optional nhưng đề cho phép).

    Cần code bên trong (ý tưởng):
    - sentence chứa \\cite{key}
    - heading gần nhất, kind parent
    - số lần cite trong paper
    """
    raise NotImplementedError("TODO(M3): cite_context_features")


def pair_feature_vector(bib: dict[str, Any], ref: dict[str, Any], extra: dict | None = None) -> list[float]:
    """Ghép mọi feature thành vector cố định (cột đặt tên, dump ra JSON để report)."""
    raise NotImplementedError("TODO(M3): pair_feature_vector")


def feature_names() -> list[str]:
    """Tên cột khớp pair_feature_vector — bắt buộc đồng bộ, dùng cho poster."""
    raise NotImplementedError("TODO(M3): feature_names")
