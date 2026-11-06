"""
Thống kê M2 cho Jupyter Book.

Phần cây thô (trước cleanup/dedup) đếm:
- parsing success rate, version coverage / publication
- số node/cạnh, file ignored (off compilation path)
- runtime/memory lấy từ metrics track_run nếu có
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.common import config
from src.common.ids import folder_name_for_arxiv_id
from src.common.io import write_json
from src.common.metrics import directory_size_bytes


def parsing_stats(working_dir: Path) -> dict[str, Any]:
    """
    Cần code bên trong:
    - n_versions_total, n_versions_parsed, n_versions_empty (không TeX)
    - n_elements_before_dedup vs after
    - n_bib_before vs after
    - files ignored (off compilation path)
    """
    root = Path(working_dir)
    n_publications = 0
    n_versions_total = 0
    n_versions_parsed = 0
    n_versions_empty = 0
    n_nodes = 0
    n_edges = 0
    n_unused_files = 0
    n_compilation_files = 0
    kinds: dict[str, int] = {}
    papers_all_empty = 0
    papers_any_parsed = 0

    for arxiv_id in _iter_working_publications(root):
        n_publications += 1
        index_path = root / folder_name_for_arxiv_id(arxiv_id)
        raw_index = index_path / "parsed" / "raw" / "index.json"
        if not raw_index.exists():
            continue
        try:
            payload = json.loads(raw_index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n_versions_total += int(payload.get("n_versions") or 0)
        n_versions_parsed += int(payload.get("n_parsed") or 0)
        n_versions_empty += int(payload.get("n_empty") or 0)
        if payload.get("n_parsed"):
            papers_any_parsed += 1
        elif payload.get("n_versions"):
            papers_all_empty += 1
        for version_info in payload.get("versions") or []:
            n_nodes += int(version_info.get("n_nodes") or 0)
            n_edges += int(version_info.get("n_edges") or 0)
            n_unused_files += int(version_info.get("n_unused_files") or 0)
            n_compilation_files += int(version_info.get("n_compilation_files") or 0)
            meta = (
                index_path
                / "parsed"
                / "raw"
                / f"v{version_info.get('version')}"
                / "nodes.jsonl"
            )
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        kind = json.loads(line).get("kind") or "unknown"
                    except ValueError:
                        continue
                    kinds[kind] = kinds.get(kind, 0) + 1

    success_rate = (
        n_versions_parsed / n_versions_total if n_versions_total else 0.0
    )
    return {
        "n_publications": n_publications,
        "n_versions_total": n_versions_total,
        "n_versions_parsed": n_versions_parsed,
        "n_versions_empty": n_versions_empty,
        "version_success_rate": success_rate,
        "papers_any_parsed": papers_any_parsed,
        "papers_all_empty": papers_all_empty,
        "n_nodes_before_dedup": n_nodes,
        "n_edges_before_dedup": n_edges,
        "n_elements_after_dedup": None,
        "n_bib_before": None,
        "n_bib_after": None,
        "n_compilation_files": n_compilation_files,
        "n_unused_tex_files": n_unused_files,
        "kind_counts": kinds,
        "normalized": False,
        "output_bytes": _raw_output_bytes(root),
    }


def _iter_working_publications(working_dir: Path) -> list[str]:
    """arXiv ids có paper.json trong corpus M1 (không import pipeline để tránh vòng)."""
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
                payload = json.loads(paper_json.read_text(encoding="utf-8"))
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


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Ghi data/tables/metrics_m2.json."""
    dest = path if path is not None else Path(config.TABLES_DIR) / "metrics_m2.json"
    write_json(dest, payload)
    return dest


def _raw_output_bytes(working_dir: Path) -> int:
    total = 0
    if not working_dir.is_dir():
        return 0
    for parsed in working_dir.glob("*/parsed/raw"):
        total += directory_size_bytes(parsed)
    tables = Path(config.TABLES_DIR)
    for name in ("raw_nodes.jsonl", "raw_edges.jsonl", "raw_parse_index.json", "metrics_m2_raw.json"):
        file_path = tables / name
        if file_path.exists():
            total += file_path.stat().st_size
    return total
