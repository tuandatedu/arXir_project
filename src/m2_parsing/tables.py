"""Persist and validate the three flattened M2 tables."""

from __future__ import annotations

from pathlib import Path

from src.common import config
from src.common.ids import folder_name_for_arxiv_id
from src.common.io import dataclass_to_dict, write_jsonl
from src.common.schemas import BIBTEX_ENTRY_TYPES, ELEMENT_KINDS, BibtexRow, ElementRow, HierarchyRow


def validate_m2_tables(elements: list[ElementRow], hierarchy: list[HierarchyRow], bibtex: list[BibtexRow]) -> None:
    ids = {row.element_id: row for row in elements}
    if len(ids) != len(elements):
        raise ValueError("Duplicate element_id")
    if any(row.kind not in ELEMENT_KINDS or not row.element_id or not row.arxiv_id
           or not isinstance(row.content, str) for row in elements):
        raise ValueError("Invalid elements row")
    for edge in hierarchy:
        child, parent = ids.get(edge.element_id), ids.get(edge.parent_id)
        if not child or not parent or child.arxiv_id != edge.arxiv_id or parent.arxiv_id != edge.arxiv_id:
            raise ValueError(f"Broken hierarchy edge: {edge}")
        if edge.element_id == edge.parent_id or edge.version < 1:
            raise ValueError(f"Invalid hierarchy edge: {edge}")
    keys = [(row.arxiv_id, row.citation_key) for row in bibtex]
    if len(keys) != len(set(keys)) or any(
        not row.arxiv_id or not row.citation_key or row.entry_type not in BIBTEX_ENTRY_TYPES
        or not isinstance(row.authors, list) or not all(isinstance(a, str) for a in row.authors)
        or (row.year is not None and not isinstance(row.year, int))
        for row in bibtex
    ):
        raise ValueError("Invalid BibTeX rows")


def write_m2_tables(elements: list[ElementRow], hierarchy: list[HierarchyRow], bibtex: list[BibtexRow],
                    tables_dir: Path | None = None) -> None:
    validate_m2_tables(elements, hierarchy, bibtex)
    root = Path(tables_dir) if tables_dir is not None else Path(config.TABLES_DIR)
    for name, rows in (("elements", elements), ("hierarchy", hierarchy), ("bibtex", bibtex)):
        write_jsonl(root / f"{name}.jsonl", (dataclass_to_dict(row) for row in rows))


def save_publication_parsed(arxiv_id: str, elements: list[ElementRow], hierarchy: list[HierarchyRow],
                            bibtex: list[BibtexRow], working_dir: Path | None = None) -> None:
    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    parsed = root / folder_name_for_arxiv_id(arxiv_id) / "parsed"
    for name, rows in (("elements", elements), ("hierarchy", hierarchy), ("bibtex", bibtex)):
        write_jsonl(parsed / f"{name}.jsonl", (dataclass_to_dict(row) for row in rows))
