"""Ghi 3 bảng M2: elements, hierarchy, bibtex (working jsonl; parquet ở M3)."""

from __future__ import annotations

from src.common.schemas import BibtexRow, ElementRow, HierarchyRow


def write_m2_tables(
    elements: list[ElementRow],
    hierarchy: list[HierarchyRow],
    bibtex: list[BibtexRow],
) -> None:
    """Ghi data/tables/elements.jsonl, hierarchy.jsonl, bibtex.jsonl."""
    raise NotImplementedError("TODO(M2): write_m2_tables")


def save_publication_parsed(
    arxiv_id: str,
    elements: list[ElementRow],
    hierarchy: list[HierarchyRow],
    bibtex: list[BibtexRow],
) -> None:
    """
    Working folder parsed / publication (gợi ý đề):
    data/working/{id}/parsed/elements.jsonl + hierarchy.jsonl + bibtex.json
    để M3 không phải parse lại.
    """
    raise NotImplementedError("TODO(M2): save_publication_parsed")
