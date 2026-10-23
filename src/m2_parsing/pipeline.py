"""Orchestrator M2: mỗi publication M1 → tree / version → cleanup → dedup → 3 bảng."""

from __future__ import annotations

from src.common.schemas import BibtexRow, ElementRow, HierarchyRow


def parse_one_version(arxiv_id: str, version: int) -> object:
    """
    1 version: compilation_path → cleanup_document → parse_tex_to_tree + collect bib.

    Cần code bên trong:
    - source_dir rỗng / không root → tree rỗng + bib [] (vẫn record version).
    - Return ParseNode + raw bib entries.
    """
    raise NotImplementedError("TODO(M2): parse_one_version")


def parse_one_publication(arxiv_id: str) -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """Mọi version của 1 paper: parse → assign_element_ids → dedup_bibtex_across_versions."""
    raise NotImplementedError("TODO(M2): parse_one_publication")


def run_milestone2() -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """
    Entry chính M2.

    Cần code bên trong:
    - iter_publications() từ M1
    - track_run('m2')
    - concat all rows, write_m2_tables + per-publication parsed + metrics
    """
    raise NotImplementedError("TODO(M2): run_milestone2")
