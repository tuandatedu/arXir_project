"""Orchestrator M2: mỗi publication M1 → tree / version (trước chuẩn hóa).

Cleanup, BibTeX và dedup across versions thuộc phần việc khác của nhóm.
Module này bàn giao cây cha–con thô của từng version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common import config
from src.common.ids import folder_name_for_arxiv_id, normalize_arxiv_id
from src.common.io import write_json, write_jsonl
from src.common.metrics import track_run
from src.common.schemas import BibtexRow, ElementRow, HierarchyRow

from .gather import compilation_path, concatenate_compilation_tex, find_document_root, unused_tex_files
from .hierarchy import ParseNode, nodes_and_edges, parse_tex_to_tree

LOG = logging.getLogger(__name__)


@dataclass
class VersionParseResult:
    """Cây một version, trước cleanup / dedup."""

    arxiv_id: str
    version: int
    empty: bool
    reason: str = ""
    tree: ParseNode = field(default_factory=lambda: ParseNode(kind="document", content=""))
    compilation_files: list[str] = field(default_factory=list)
    unused_files: list[str] = field(default_factory=list)
    n_nodes: int = 0
    n_edges: int = 0

    def to_payload(self) -> dict[str, Any]:
        nodes, edges = nodes_and_edges(self.tree, version=self.version)
        return {
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "empty": self.empty,
            "reason": self.reason,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "compilation_files": self.compilation_files,
            "unused_files": self.unused_files,
            "tree": self.tree.to_dict(),
            "nodes": nodes,
            "edges": edges,
        }


def list_local_versions(arxiv_id: str, working_dir: Path | None = None) -> list[int]:
    """Các thư mục vN có mặt trong corpus M1 (kể cả empty)."""
    pub = _publication_dir(arxiv_id, working_dir)
    if not pub.is_dir():
        return []
    versions: list[int] = []
    for child in pub.iterdir():
        if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
            versions.append(int(child.name[1:]))
    return sorted(versions)


def parse_one_version(
    arxiv_id: str,
    version: int,
    working_dir: Path | None = None,
) -> VersionParseResult:
    """
    1 version: compilation_path → parse_tex_to_tree (KHÔNG cleanup).

    Cần code bên trong:
    - source_dir rỗng / không root → tree rỗng + bib [] (vẫn record version).
    - Return ParseNode + raw bib entries.
    """
    base = normalize_arxiv_id(arxiv_id)
    source_dir = _version_source_dir(base, version, working_dir)
    version_dir = source_dir.parent
    empty_marker = version_dir / "empty.json"

    def empty(reason: str) -> VersionParseResult:
        tree = parse_tex_to_tree("")
        nodes, edges = nodes_and_edges(tree, version=version)
        return VersionParseResult(
            arxiv_id=base,
            version=version,
            empty=True,
            reason=reason,
            tree=tree,
            n_nodes=len(nodes),
            n_edges=len(edges),
        )

    if empty_marker.exists():
        return empty("empty record from M1")
    if not source_dir.is_dir():
        return empty("missing sources directory")

    root = find_document_root(source_dir)
    if root is None:
        return empty("no \\documentclass root")

    path = compilation_path(source_dir)
    unused = unused_tex_files(source_dir)
    tex = concatenate_compilation_tex(source_dir)
    tree = parse_tex_to_tree(tex)
    nodes, edges = nodes_and_edges(tree, version=version)
    return VersionParseResult(
        arxiv_id=base,
        version=version,
        empty=False,
        tree=tree,
        compilation_files=[_rel(source_dir, p) for p in path],
        unused_files=[_rel(source_dir, p) for p in unused],
        n_nodes=len(nodes),
        n_edges=len(edges),
    )


def parse_one_publication(arxiv_id: str) -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """Mọi version của 1 paper: parse → assign_element_ids → dedup_bibtex_across_versions."""
    raise NotImplementedError(
        "TODO(M2): parse_one_publication needs cleanup + dedup. "
        "Use parse_one_version / run_raw_hierarchy for the pre-normalization tree."
    )


def run_raw_hierarchy(
    working_dir: Path | None = None,
    arxiv_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse mọi publication/version → ghi cây thô + cạnh cha–con."""
    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    ids = arxiv_ids if arxiv_ids is not None else _iter_publications(root)
    summaries: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []

    with track_run("m2_raw_hierarchy") as run_metrics:
        for raw_id in ids:
            try:
                base = normalize_arxiv_id(raw_id)
            except ValueError:
                LOG.warning("Skip invalid id %s", raw_id)
                continue
            versions = list_local_versions(base, root)
            pub_summary: dict[str, Any] = {
                "arxiv_id": base,
                "n_versions": len(versions),
                "n_empty": 0,
                "n_parsed": 0,
                "versions": [],
            }
            for version in versions:
                result = parse_one_version(base, version, working_dir=root)
                payload = result.to_payload()
                _save_raw_version(base, result, working_dir=root)
                if result.empty:
                    pub_summary["n_empty"] += 1
                else:
                    pub_summary["n_parsed"] += 1
                pub_summary["versions"].append(
                    {
                        "version": version,
                        "empty": result.empty,
                        "reason": result.reason,
                        "n_nodes": result.n_nodes,
                        "n_edges": result.n_edges,
                        "n_compilation_files": len(result.compilation_files),
                        "n_unused_files": len(result.unused_files),
                    }
                )
                for node in payload["nodes"]:
                    all_nodes.append(
                        {"arxiv_id": base, "version": version, **node}
                    )
                for edge in payload["edges"]:
                    all_edges.append({"arxiv_id": base, **edge})
            _save_raw_publication_index(base, pub_summary, working_dir=root)
            summaries.append(pub_summary)

        run_metrics["n_publications"] = len(summaries)
        run_metrics["n_versions"] = sum(s["n_versions"] for s in summaries)
        run_metrics["n_empty_versions"] = sum(s["n_empty"] for s in summaries)

    tables = Path(config.TABLES_DIR)
    write_json(tables / "raw_parse_index.json", summaries)
    write_jsonl(tables / "raw_nodes.jsonl", all_nodes)
    write_jsonl(tables / "raw_edges.jsonl", all_edges)
    from .analyze import parsing_stats, write_metrics

    stats = parsing_stats(root)
    write_metrics(stats)
    return summaries


def run_milestone2() -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """
    Entry chính M2.

    Phần cây trước chuẩn hóa chạy qua run_raw_hierarchy.
    Bảng elements/hierarchy/bibtex (sau cleanup + dedup) vẫn là TODO nhóm.
    """
    run_raw_hierarchy()
    raise NotImplementedError(
        "Raw trees written. Full M2 tables require cleanup.py, bibitem.py, dedup.py."
    )


def _publication_dir(arxiv_id: str, working_dir: Path | None) -> Path:
    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    return root / folder_name_for_arxiv_id(arxiv_id)


def _version_source_dir(arxiv_id: str, version: int, working_dir: Path | None) -> Path:
    return _publication_dir(arxiv_id, working_dir) / f"v{version}" / "sources"


def _iter_publications(working_dir: Path) -> list[str]:
    """Liệt kê arXiv id đã crawl, không import crawler M1 (tránh phụ thuộc requests)."""
    root = Path(working_dir)
    if not root.is_dir():
        return []
    ids: list[str] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        paper_json = folder / "paper.json"
        if paper_json.exists():
            try:
                payload = __import__("json").loads(paper_json.read_text(encoding="utf-8"))
                ids.append(str(payload["arxiv_id"]))
                continue
            except (ValueError, KeyError, OSError):
                pass
        name = folder.name
        if "_" in name:
            ids.append(name.replace("_", "/", 1))
        elif "-" in name:
            ids.append(name.replace("-", ".", 1))
    return ids


def _rel(source_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(source_dir).resolve()).as_posix()
    except ValueError:
        return path.name


def _save_raw_version(
    arxiv_id: str,
    result: VersionParseResult,
    working_dir: Path | None,
) -> None:
    payload = result.to_payload()
    dest = _publication_dir(arxiv_id, working_dir) / "parsed" / "raw" / f"v{result.version}"
    write_json(dest / "tree.json", payload["tree"])
    write_jsonl(dest / "nodes.jsonl", payload["nodes"])
    write_jsonl(dest / "edges.jsonl", payload["edges"])
    write_json(
        dest / "meta.json",
        {
            "arxiv_id": result.arxiv_id,
            "version": result.version,
            "empty": result.empty,
            "reason": result.reason,
            "n_nodes": result.n_nodes,
            "n_edges": result.n_edges,
            "compilation_files": result.compilation_files,
            "unused_files": result.unused_files,
            "normalized": False,
        },
    )


def _save_raw_publication_index(
    arxiv_id: str, summary: dict[str, Any], working_dir: Path | None
) -> None:
    dest = _publication_dir(arxiv_id, working_dir) / "parsed" / "raw" / "index.json"
    write_json(dest, summary)
