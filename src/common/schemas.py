"""
Schema 6 bảng Hugging Face (Parquet, cột phẳng).

Nguồn:
- papers, references: M1
- elements, hierarchy, bibtex: M2
- predictions: M3

Cột authors / revised_dates được phép là list[str] một cấp.
KHÔNG được nest object hoặc nhét JSON blob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# M1
# ---------------------------------------------------------------------------
@dataclass
class PaperRow:
    """Một publication (không phải một version)."""

    arxiv_id: str  # non-null, dạng 2310.12345 (không folder-ize)
    title: str
    authors: list[str]
    submission_date: str  # ISO
    revised_dates: list[str]  # ISO, các lần revise sau submission
    venue: Optional[str] = None


@dataclass
class ReferenceRow:
    """
    Một crawled reference CÓ arXiv ID, gắn với paper đang cite.

    Đề: bảng references chỉ giữ reference mang arXiv ID (matching pool của M3).
    Local corpus M1 nên lưu thêm cả reference không có arXiv ID.
    """

    arxiv_id: str  # citing paper, non-null
    ref_arxiv_id: str  # non-null; giữ cả scheme cũ hep-th/9901001
    ref_title: str
    ref_authors: list[str]
    ref_submission_date: str
    ref_s2_id: str  # Semantic Scholar paperId


# ---------------------------------------------------------------------------
# M2
# ---------------------------------------------------------------------------
# kind là dictionary (cột categorical). Mở rộng nếu parser cần, nhưng phải thống nhất.
ELEMENT_KINDS = (
    "document",
    "heading",
    "paragraph",
    "list",
    "list_item",
    "sentence",
    "formula",
    "figure",
    "acknowledgement",
    "appendix",
)


@dataclass
class ElementRow:
    """
    Một element duy nhất trên mọi version của publication.

    element_id: "{arxiv-key}#{discriminant}", ví dụ 2310-12345#s1
    Content trùng nhau sau cleanup → cùng một hàng (dedup full-text).
    """

    element_id: str
    arxiv_id: str
    kind: str
    content: str


@dataclass
class HierarchyRow:
    """Một cạnh parent → node trong cây của MỘT version."""

    arxiv_id: str
    version: int
    element_id: str
    parent_id: str


BIBTEX_ENTRY_TYPES = (
    "article",
    "inproceedings",
    "book",
    "incollection",
    "phdthesis",
    "mastersthesis",
    "misc",
    "unpublished",
    "techreport",
)


@dataclass
class BibtexRow:
    """Entry BibTeX đã union field + chọn 1 citation_key trên mọi version."""

    arxiv_id: str
    citation_key: str
    entry_type: str
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# M3
# ---------------------------------------------------------------------------
@dataclass
class PredictionRow:
    """
    Một hàng / BibTeX entry của publication nằm trong train/valid/test.

    Publication không tham gia matching task → không có hàng.
    """

    arxiv_id: str
    partition: str  # train | valid | test
    citation_key: str
    groundtruth_arxiv_id: Optional[str]  # None nếu không có true reference
    cand_1: Optional[str] = None
    cand_2: Optional[str] = None
    cand_3: Optional[str] = None
    cand_4: Optional[str] = None
    cand_5: Optional[str] = None
