"""Publication-scoped BibTeX and full-text deduplication."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from src.common.ids import folder_name_for_arxiv_id
from src.common.schemas import BIBTEX_ENTRY_TYPES, ELEMENT_KINDS, BibtexRow, ElementRow, HierarchyRow

from .cleanup import cleanup_element_content
from .hierarchy import ParseNode


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def references_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Match on DOI, otherwise title with compatible year/author evidence."""
    da, db = _norm(a.get("doi")), _norm(b.get("doi"))
    if da and db:
        return da == db
    ta, tb = _norm(a.get("title")), _norm(b.get("title"))
    if ta and tb:
        if ta != tb:
            return False
        if a.get("year") and b.get("year") and a["year"] != b["year"]:
            return False
        aa = {_norm(x) for x in a.get("authors") or []}
        bb = {_norm(x) for x in b.get("authors") or []}
        return not aa or not bb or bool(aa & bb)
    # Same key is useful when a sparse version lacks identifying metadata.
    return bool(a.get("citation_key") == b.get("citation_key") and not (ta and tb))


def choose_canonical_key(keys: list[str]) -> str:
    """Most frequent key, then first encountered, for deterministic citation rewrites."""
    counts = Counter(keys)
    return min(counts, key=lambda key: (-counts[key], keys.index(key)))


def union_bib_fields(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Union nonempty fields; prefer richer records for conflicting scalar values."""
    if not entries:
        return {}
    ranked = sorted(enumerate(entries), key=lambda item: (-sum(bool(v) for v in item[1].values()), -int(item[1].get("_version", 0)), item[0]))
    result: dict[str, Any] = {}
    for _, entry in ranked:
        for key, value in entry.items():
            if key.startswith("_") or value in (None, "", []):
                continue
            if key == "authors":
                names = result.setdefault("authors", [])
                seen = {_norm(name) for name in names}
                for name in value:
                    if _norm(name) not in seen:
                        names.append(name)
                        seen.add(_norm(name))
            else:
                result.setdefault(key, value)
    return result


def dedup_bibtex_across_versions(
    per_version_entries: dict[int, list[dict[str, Any]]],
) -> tuple[list[BibtexRow], dict[str, str]]:
    """Cluster references across versions, merge fields and map old citation keys."""
    all_entries = [{**entry, "_version": version} for version in sorted(per_version_entries)
                   for entry in per_version_entries[version] if entry.get("citation_key")]
    roots = list(range(len(all_entries)))

    def find(i: int) -> int:
        while roots[i] != i:
            roots[i] = roots[roots[i]]
            i = roots[i]
        return i

    for i, entry in enumerate(all_entries):
        for j in range(i):
            if references_similar(entry, all_entries[j]):
                roots[find(i)] = find(j)
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, entry in enumerate(all_entries):
        groups[find(i)].append(entry)
    rows: list[BibtexRow] = []
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for cluster in groups.values():
        fields = union_bib_fields(cluster)
        key = choose_canonical_key([entry["citation_key"] for entry in cluster])
        original_key = key
        suffix = 2
        while key in used:
            key = f"{original_key}_{suffix}"
            suffix += 1
        used.add(key)
        for entry in cluster:
            old_key = entry["citation_key"]
            version_key = f"v{entry['_version']}:{old_key}"
            mapping.setdefault(version_key, key)
        typ = fields.get("entry_type", "misc")
        rows.append(BibtexRow(
            arxiv_id="", citation_key=key,
            entry_type=typ if typ in BIBTEX_ENTRY_TYPES else "misc",
            title=fields.get("title"), authors=fields.get("authors", []),
            year=fields.get("year"), doi=fields.get("doi"),
            journal=fields.get("journal"), url=fields.get("url"),
        ))
    by_old_key: dict[str, set[str]] = defaultdict(set)
    for entry in all_entries:
        old_key = entry["citation_key"]
        by_old_key[old_key].add(mapping[f"v{entry['_version']}:{old_key}"])
    mapping.update({old: next(iter(values)) for old, values in by_old_key.items() if len(values) == 1})
    return rows, mapping


_CITE = re.compile(r"\\(cite[a-zA-Z]*\*?)(\[[^\]]*\])*\{([^{}]+)\}")


def rewrite_citations(content: str, mapping: dict[str, str]) -> str:
    """Rename comma-separated keys in LaTeX citation commands."""
    def replace(match: re.Match[str]) -> str:
        keys = [mapping.get(key.strip(), key.strip()) for key in match[3].split(",")]
        return match[0][:match[0].rfind("{") + 1] + ",".join(keys) + "}"
    return _CITE.sub(replace, content)


def flatten_tree_with_placeholders(root: ParseNode) -> list[tuple[ParseNode, ParseNode | None]]:
    items: list[tuple[ParseNode, ParseNode | None]] = []
    def walk(node: ParseNode, parent: ParseNode | None) -> None:
        items.append((node, parent))
        for child in node.children:
            walk(child, node)
    walk(root, None)
    return items


def assign_element_ids(
    arxiv_id: str,
    trees_by_version: dict[int, ParseNode],
) -> tuple[list[ElementRow], list[HierarchyRow]]:
    """Share IDs for identical cleaned kind/content across a publication's versions."""
    prefix = folder_name_for_arxiv_id(arxiv_id)
    counts: dict[str, int] = defaultdict(int)
    seen: dict[tuple[str, str], str] = {}
    elements: list[ElementRow] = []
    edges: list[HierarchyRow] = []
    codes = {"document": "root", "heading": "h", "sentence": "s", "paragraph": "p",
             "formula": "f", "figure": "fig", "list": "l", "list_item": "i",
             "acknowledgement": "ack", "appendix": "app"}
    for version, root in sorted(trees_by_version.items()):
        if not root.children and not root.content.strip():
            continue  # Empty M1 versions have no elements.
        ids: dict[int, str] = {}
        for node, parent in flatten_tree_with_placeholders(root):
            if node.kind not in ELEMENT_KINDS:
                raise ValueError(f"Unknown element kind: {node.kind}")
            content = cleanup_element_content(node.content)
            key = (node.kind, content)
            if node is root:
                key = (node.kind, f"{content}\0v{version}")  # per-version root
            if key not in seen:
                code = codes[node.kind]
                counts[code] += 1
                eid = f"{prefix}#{code}{counts[code]}"
                seen[key] = eid
                elements.append(ElementRow(eid, arxiv_id, node.kind, content))
            ids[id(node)] = seen[key]
            if parent is not None:
                edges.append(HierarchyRow(arxiv_id, version, ids[id(node)], ids[id(parent)]))
    # The schema has one row per node-parent edge, even if repeated identical leaves collapse.
    edges = list(dict.fromkeys((r.arxiv_id, r.version, r.element_id, r.parent_id) for r in edges))
    return elements, [HierarchyRow(*edge) for edge in edges]
