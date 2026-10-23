"""
Crawl reference metadata qua Semantic Scholar Graph API.

Endpoint: https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}
Fields (flat, không nest authors.name): references.title, authors, year,
publicationDate, venue, externalIds.

Bảng Hugging Face `references` CHỈ giữ reference có ArXiv ID.
Working corpus PHẢI lưu mọi reference (kể cả không có arXiv ID).
"""

from __future__ import annotations

from typing import Any, Optional


def fetch_s2_references(arxiv_id: str, api_key: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Gọi S2, trả list raw reference objects.

    Cần code bên trong:
    - URL = S2_PAPER_URL.format(arxiv_id=arxiv_id), params fields=S2_FIELDS.
    - Header x-api-key nếu có (env S2_API_KEY) — unauth: 1 req/s + 100/5 phút.
    - Rate-limit S2_MIN_DELAY_SEC, retry 429.
    - Paper mới / chưa index: trả [] và log warning, không crash pipeline.
    - KHÔNG dùng nested field `authors.name` (API reject).
    """
    raise NotImplementedError("TODO(M1): fetch_s2_references")


def extract_arxiv_id_from_external_ids(external_ids: dict[str, Any] | None) -> Optional[str]:
    """
    Lấy key 'ArXiv' từ externalIds. Giữ nguyên scheme cũ hep-th/9901001.

    Cần code bên trong:
    - None / thiếu key → None (reference không vào bảng HF, vẫn lưu local).
    - normalize_arxiv_id nếu cần, nhưng đừng đổi archive/YYMMNNN.
    """
    raise NotImplementedError("TODO(M1): extract_arxiv_id_from_external_ids")


def s2_ref_to_local_record(citing_arxiv_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """
    Chuẩn hóa 1 reference S2 thành record local (giữ cả khi không có ArXiv).

    Cần code bên trong — các field đề yêu cầu lưu:
    - citing arxiv_id
    - ref_title, ref_authors (list[str] từ objects {authorId, name})
    - ref_submission_date (publicationDate hoặc year)
    - ref_arxiv_id (nullable ở local)
    - ref_s2_id = paperId
    - venue, year (optional, tiện M3)
    """
    raise NotImplementedError("TODO(M1): s2_ref_to_local_record")
