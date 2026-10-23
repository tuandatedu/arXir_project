"""
\\bibitem trong .tex → BibTeX (regex / parser). Cũng đọc file .bib nếu có trên corpus.

Output tạm: list entry {citation_key, entry_type, fields...} per version,
rồi dedup.py union across versions.
"""

from __future__ import annotations

from typing import Any


def extract_bibitems(tex: str) -> list[dict[str, Any]]:
    """
    Parse thebibliography / \\bibitem{key} ...

    Cần code bên trong:
    - Regex \\bibitem[optional]{key} tới bibitem kế / \\end{thebibliography}
    - Đoán entry_type (article/inproceedings/misc) từ journal/booktitle nếu có
    - Tách title, authors (and), year, doi, url, journal
    - Key = citation_key
    """
    raise NotImplementedError("TODO(M2): extract_bibitems")


def parse_bib_file(bib_text: str) -> list[dict[str, Any]]:
    """
    Parse .bib native (nếu paper nộp sẵn BibTeX).

    Cần code bên trong: dùng bibtexparser hoặc regex @article{key, ...}
    """
    raise NotImplementedError("TODO(M2): parse_bib_file")


def infer_entry_type(fields: dict[str, Any]) -> str:
    """Heuristic: journal→article, booktitle→inproceedings, else misc. Phải thuộc BIBTEX_ENTRY_TYPES."""
    raise NotImplementedError("TODO(M2): infer_entry_type")


def collect_version_bibtex(source_dir, cleaned_tex: str) -> list[dict[str, Any]]:
    """Gộp bibitem từ tex + mọi file .bib trong source_dir (compilation không bắt buộc chứa .bib)."""
    raise NotImplementedError("TODO(M2): collect_version_bibtex")
