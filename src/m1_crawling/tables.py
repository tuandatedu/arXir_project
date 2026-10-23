"""
Xuất 2 bảng M1 (schema Hugging Face, cột phẳng).

papers: 1 hàng / publication (không phải / version).
references: 1 hàng / crawled reference CÓ arXiv ID + citing paper.
"""

from __future__ import annotations

from src.common.schemas import PaperRow, ReferenceRow

from .discover import PaperMeta


def paper_meta_to_row(meta: PaperMeta) -> PaperRow:
    """Map PaperMeta → PaperRow (arxiv_id base, không kèm vN)."""
    raise NotImplementedError("TODO(M1): paper_meta_to_row")


def s2_records_to_reference_rows(
    citing_arxiv_id: str,
    records: list[dict],
) -> list[ReferenceRow]:
    """
    Lọc local S2 records → chỉ hàng có ref_arxiv_id.

    Cần code bên trong:
    - Bỏ record thiếu ArXiv (vẫn nằm trong references_s2.json).
    - ref_submission_date: string (ISO nếu có, không thì year dạng '2017').
    """
    raise NotImplementedError("TODO(M1): s2_records_to_reference_rows")


def write_m1_tables(papers: list[PaperRow], references: list[ReferenceRow]) -> None:
    """
    Ghi data/tables/papers.jsonl + references.jsonl (working).
    Parquet sharded nằm ở bước export HF (M3).
    """
    raise NotImplementedError("TODO(M1): write_m1_tables")
