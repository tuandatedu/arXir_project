"""
Bài toán: với paper có m BibTeX entries và n crawled refs (có arXiv ID),
ma trận nhị phân m×n. Mỗi labeled entry = 1 hàng: đúng 1 ô yes nếu có GT, hoặc toàn no.

Nhóm chọn paradigm (classification / ranking / ...) và ghi poster.

Output serving: top-5 ref_arxiv_id / entry (cand_1 tốt nhất).
Post-processing được phép (ví dụ: unique candidates, ưu tiên DOI exact).
"""

from __future__ import annotations

from typing import Any


def build_candidate_matrix(
    arxiv_id: str,
    labels_for_paper: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[list[int]]]:
    """
    Trả (citation_keys, ref_arxiv_ids, matrix 0/1).

    Cần code bên trong:
    - Chỉ entry đã label mới có hàng
    - GT không nằm trong crawled refs → hàng toàn 0
    """
    raise NotImplementedError("TODO(M3): build_candidate_matrix")


def train_model(train_ids: list[str], labels: dict[str, list[dict[str, Any]]]) -> object:
    """
    Fit model trên pair features của train publications.

    Cần code bên trong:
    - Xây X, y từ pair_feature_vector (positive = GT pair, negative = cặp còn lại)
    - sklearn (LogisticRegression / GradientBoosting / ...) HOẶC ranker
    - Lưu model data/tables/model_m3.joblib (không commit binary lớn nếu không cần)
    """
    raise NotImplementedError("TODO(M3): train_model")


def predict_top5(
    model: object,
    arxiv_id: str,
    citation_key: str,
) -> list[str | None]:
    """
    Ranked list length 5 (pad None nếu n < 5).

    Cần code bên trong:
    - Score mọi ref của cùng paper
    - Sort desc, cắt 5
    - Post-process (dedup, exact-title boost) — được đề cho phép
    """
    raise NotImplementedError("TODO(M3): predict_top5")
