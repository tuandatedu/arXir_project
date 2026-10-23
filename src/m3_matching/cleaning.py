"""
Text preprocessing thêm cho matching (sau M2).

Gợi ý đề: lowercase, stop-word, tokenize riêng author vs title.
"""

from __future__ import annotations


def normalize_title(title: str) -> str:
    """
    Cần code bên trong:
    - lower, bỏ punctuation dư, collapse space
    - tùy chọn: stopwords, stem/lemmatize (ghi poster vì sao dùng)
    """
    raise NotImplementedError("TODO(M3): normalize_title")


def normalize_authors(authors: list[str]) -> list[str]:
    """
    Cần code bên trong:
    - 'Vaswani, Ashish' vs 'Ashish Vaswani' → canonical last-name + initials
    - lower, bỏ dấu unicode
    """
    raise NotImplementedError("TODO(M3): normalize_authors")


def normalize_year(value: object) -> int | None:
    """Parse year từ int / '2017' / ISO date. Fail → None."""
    raise NotImplementedError("TODO(M3): normalize_year")


def prepare_bibtex_record(row: dict) -> dict:
    """Thêm field *_norm cho 1 BibTeX row (không sửa bảng gốc)."""
    raise NotImplementedError("TODO(M3): prepare_bibtex_record")


def prepare_reference_record(row: dict) -> dict:
    """Thêm field *_norm cho 1 crawled reference (có arXiv ID)."""
    raise NotImplementedError("TODO(M3): prepare_reference_record")
