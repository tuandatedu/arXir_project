"""
Layout working corpus M1 (gợi ý đề, nhóm được phép chỉnh nếu ghi README).

data/working/{folder_id}/
  paper.json                 # metadata publication (title, authors, dates, venue)
  references_s2.json         # MỌI crawled reference (kể cả không có arXiv ID)
  v1/
    metadata.json            # metadata riêng version (nếu khác latest)
    sources/                 # chỉ .tex / .bib đã extract
  v2/
    ...
  empty_vN.json              # version PDF-only / không TeX: empty record, KHÔNG drop paper
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .discover import PaperMeta


def publication_dir(arxiv_id: str) -> Path:
    """data/working/{folder_name_for_arxiv_id}."""
    raise NotImplementedError("TODO(M1): publication_dir")


def version_source_dir(arxiv_id: str, version: int) -> Path:
    """data/working/{id}/v{N}/sources/."""
    raise NotImplementedError("TODO(M1): version_source_dir")


def save_paper_meta(arxiv_id: str, meta: PaperMeta) -> Path:
    """Ghi paper.json (title, authors, submission_date, revised_dates, venue, versions)."""
    raise NotImplementedError("TODO(M1): save_paper_meta")


def save_version_sources(
    arxiv_id: str,
    version: int,
    extracted_files: list[Path],
    *,
    empty: bool,
    reason: str = "",
) -> None:
    """
    Copy/ghi sources vào vN/sources, hoặc ghi empty record nếu empty=True.

    Cần code bên trong:
    - empty=True: KHÔNG xóa publication; ghi marker (empty.json) + reason (pdf-only, no tex, 404).
    - empty=False: giữ relative path, không sửa nội dung TeX.
    """
    raise NotImplementedError("TODO(M1): save_version_sources")


def save_s2_references(arxiv_id: str, records: list[dict[str, Any]]) -> Path:
    """Ghi references_s2.json (toàn bộ S2 refs của publication)."""
    raise NotImplementedError("TODO(M1): save_s2_references")


def iter_publications(working_dir: Path | None = None) -> list[str]:
    """Liệt kê arxiv_id đã crawl (để M2 đọc lại, không crawl lần nữa)."""
    raise NotImplementedError("TODO(M1): iter_publications")
