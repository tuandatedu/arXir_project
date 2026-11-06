"""M2 orchestration: preserve raw parsing and build normalized final tables."""

from __future__ import annotations

import logging
import threading
import time
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
from .bibitem import collect_version_bibtex
from .cleanup import cleanup_element_content
from .dedup import assign_element_ids, dedup_bibtex_across_versions, flatten_tree_with_placeholders, rewrite_citations
from .tables import save_publication_parsed, write_m2_tables

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
    source_tex: str = ""  # transient; omitted from serialized parse metadata

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

    path = compilation_path(source_dir, root=root)
    unused = unused_tex_files(source_dir, used_paths=path)
    tex = concatenate_compilation_tex(source_dir, root=root)
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
        source_tex=tex,
    )


def parse_one_publication(
    arxiv_id: str, working_dir: Path | None = None,
) -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """Parse all versions, merge references, rewrite citations and deduplicate."""
    base = normalize_arxiv_id(arxiv_id)
    trees: dict[int, ParseNode] = {}
    references: dict[int, list[dict[str, Any]]] = {}
    for version in list_local_versions(base, working_dir):
        result = parse_one_version(base, version, working_dir)
        trees[version] = result.tree
        if result.empty:
            references[version] = []
        else:
            source_dir = _version_source_dir(base, version, working_dir)
            references[version] = collect_version_bibtex(source_dir, result.source_tex)
    return _finalize_publication(base, trees, references)


def _finalize_publication(
    base: str, trees: dict[int, ParseNode], references: dict[int, list[dict[str, Any]]],
) -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    bibtex, key_map = dedup_bibtex_across_versions(references)
    for row in bibtex:
        row.arxiv_id = base
    for version, root in trees.items():
        version_map = {**{k: v for k, v in key_map.items() if not k.startswith("v") or ":" not in k},
                       **{k.split(":", 1)[1]: v for k, v in key_map.items() if k.startswith(f"v{version}:")}}
        for node, _ in flatten_tree_with_placeholders(root):
            node.content = rewrite_citations(node.content, version_map)
        _prune_empty_nodes(root)
        _populate_container_content(root)
    elements, hierarchy = assign_element_ids(base, trees)
    return elements, hierarchy, bibtex


def _prune_empty_nodes(node: ParseNode) -> bool:
    """Drop leaves emptied by cleanup and their now-empty containers."""
    node.children = [child for child in node.children if _prune_empty_nodes(child)]
    if node.kind == "document":
        return True
    if node.kind in {"sentence", "formula", "figure"}:
        return bool(cleanup_element_content(node.content))
    return bool(node.children or cleanup_element_content(node.content))


def _populate_container_content(node: ParseNode) -> str:
    """Give anonymous containers their child text so distinct paragraphs stay distinct."""
    child_texts = [_populate_container_content(child) for child in node.children]
    if node.kind in {"paragraph", "list_item", "list"}:
        node.content = " ".join(text for text in child_texts if text)
    return cleanup_element_content(node.content)


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
    write_metrics(stats, tables / "metrics_m2_raw.json")
    return summaries


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


def run_milestone2(
    working_dir: Path | None = None, arxiv_ids: list[str] | None = None,
    tables_dir: Path | None = None,
) -> tuple[list[ElementRow], list[HierarchyRow], list[BibtexRow]]:
    """Run complete M2 and store per-publication plus global tables and metrics."""
    from src.common.metrics import directory_size_bytes
    from .analyze import write_metrics

    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    out = Path(tables_dir) if tables_dir is not None else Path(config.TABLES_DIR)
    ids = arxiv_ids if arxiv_ids is not None else _iter_publications(root)
    all_elements: list[ElementRow] = []
    all_edges: list[HierarchyRow] = []
    all_bibtex: list[BibtexRow] = []
    coverage: list[dict[str, Any]] = []
    start = time.perf_counter()
    try:
        import psutil
        process = psutil.Process()
        samples = [process.memory_info().rss]
    except ImportError:
        process = None
        samples = []
    stop_sampling = threading.Event()
    def sample_memory() -> None:
        while not stop_sampling.wait(0.05):
            try:
                samples.append(process.memory_info().rss)
            except Exception:
                return
    sampler = threading.Thread(target=sample_memory, daemon=True)
    if process is not None:
        sampler.start()
    for raw_id in ids:
        base = normalize_arxiv_id(raw_id)
        versions = list_local_versions(base, root)
        before_nodes = before_bib = parsed = 0
        parsed_versions: list[int] = []
        empty_versions: list[int] = []
        failed_versions: list[dict[str, Any]] = []
        trees: dict[int, ParseNode] = {}
        references: dict[int, list[dict[str, Any]]] = {}
        for version in versions:
            try:
                result = parse_one_version(base, version, root)
                trees[version] = result.tree
                if not result.empty:
                    source_dir = _version_source_dir(base, version, root)
                    references[version] = collect_version_bibtex(source_dir, result.source_tex)
                    parsed += 1
                    parsed_versions.append(version)
                    before_nodes += result.n_nodes
                else:
                    if result.reason == "empty record from M1":
                        empty_versions.append(version)
                    else:
                        failed_versions.append({"version": version, "error": result.reason})
                    references[version] = []
                before_bib += len(references[version])
            except Exception as exc:
                LOG.exception("M2 failed to parse %sv%d", base, version)
                failed_versions.append({"version": version, "error": str(exc)})
                trees[version] = ParseNode(kind="document", content="")
                references[version] = []
        try:
            elements, edges, bibtex = _finalize_publication(base, trees, references)
            save_publication_parsed(base, elements, edges, bibtex, root)
        except Exception as exc:
            LOG.exception("M2 failed to finalize %s", base)
            failed_versions = [{"version": version, "error": str(exc)} for version in versions if version not in empty_versions]
            parsed_versions = []
            parsed = 0
            elements, edges, bibtex = [], [], []
        all_elements.extend(elements)
        all_edges.extend(edges)
        all_bibtex.extend(bibtex)
        coverage.append({"arxiv_id": base, "versions": versions,
                         "parsed_versions": parsed_versions, "empty_versions": empty_versions,
                         "failed_versions": failed_versions,
                         "n_versions": len(versions),
                         "n_parsed": parsed, "n_empty": len(empty_versions),
                         "n_failed": len(failed_versions),
                         "n_elements_before_dedup": before_nodes,
                         "n_elements_after_dedup": len(elements),
                         "n_bib_before": before_bib, "n_bib_after": len(bibtex)})
        if process is not None:
            samples.append(process.memory_info().rss)
    write_m2_tables(all_elements, all_edges, all_bibtex, out)
    stop_sampling.set()
    if process is not None:
        sampler.join(timeout=0.2)
        samples.append(process.memory_info().rss)
    duration = time.perf_counter() - start
    metrics = {
        "n_publications": len(coverage), "n_versions_total": sum(x["n_versions"] for x in coverage),
        "n_versions_parsed": sum(x["n_parsed"] for x in coverage),
        "n_versions_empty": sum(x["n_empty"] for x in coverage),
        "n_versions_failed": sum(x["n_failed"] for x in coverage),
        "n_elements_before_dedup": sum(x["n_elements_before_dedup"] for x in coverage),
        "n_elements_after_dedup": len(all_elements),
        "n_bib_before": sum(x["n_bib_before"] for x in coverage),
        "n_bib_after": len(all_bibtex), "n_hierarchy_edges": len(all_edges),
        "duration_sec": round(duration, 3),
        "avg_publication_sec": round(duration / len(coverage), 3) if coverage else None,
        "peak_rss_bytes": max(samples) if samples else None,
        "output_bytes": sum(directory_size_bytes(out / f"{name}.jsonl") for name in ("elements", "hierarchy", "bibtex")),
        "coverage": coverage, "normalized": True,
    }
    metrics["version_success_rate"] = metrics["n_versions_parsed"] / metrics["n_versions_total"] if metrics["n_versions_total"] else 0.0
    write_metrics(metrics, out / "metrics_m2.json")
    return all_elements, all_edges, all_bibtex
