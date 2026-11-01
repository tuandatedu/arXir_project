"""
Thống kê corpus M1 cho Jupyter Book (figure/table generate lúc compile, không screenshot).

Đề yêu cầu tối thiểu:
- số paper crawl thành công, overall success rate
- average paper size bytes trước/sau khi bỏ figure (archive vs extracted tex/bib)
- average references / paper, success rate crawl reference metadata
- runtime: time / paper, average, total discovery time
- memory: peak RAM, average RAM, max disk, final output size
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.common import config
from src.common.io import load_assigned_ids, read_jsonl
from src.common.metrics import directory_size_bytes


def _assigned_count() -> Optional[int]:
    path = Path(config.ASSIGNED_IDS_FILE)
    if not path.exists():
        return None
    try:
        return len(load_assigned_ids(path))
    except (OSError, ValueError):
        return None


def corpus_stats(working_dir: Path | None = None) -> dict[str, Any]:
    """
    Duyệt data/working, đếm paper/version/empty/tex-size/ref coverage.

    - n_assigned, n_resolved, n_versions, n_empty_versions
    - bytes_archives (từ version metadata.json), bytes_extracted
    - n_s2_refs, n_s2_with_arxiv, avg_refs_per_paper
    - success rates + kích thước trung bình (report M1)
    """
    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    n_resolved = 0
    n_versions = 0
    n_empty_versions = 0
    n_tex_versions = 0
    n_tex_files = 0
    bytes_archives = 0
    bytes_extracted = 0
    n_s2_refs = 0
    n_s2_with_arxiv = 0
    papers_with_s2_file = 0
    papers_with_arxiv_refs = 0

    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or not (folder / "paper.json").exists():
                continue
            n_resolved += 1
            for version_dir in sorted(folder.glob("v*")):
                if not version_dir.is_dir() or not version_dir.name[1:].isdigit():
                    continue
                n_versions += 1
                metadata_path = version_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        payload = {}
                    bytes_archives += int(payload.get("archive_bytes") or 0)
                    bytes_extracted += int(payload.get("extracted_bytes") or 0)
                    if payload.get("status") == "ok":
                        n_tex_versions += 1
                        n_tex_files += int(payload.get("n_files") or 0)
                    else:
                        n_empty_versions += 1
                elif (version_dir / "empty.json").exists():
                    n_empty_versions += 1
                else:
                    sources = version_dir / "sources"
                    if sources.is_dir():
                        n_tex_versions += 1
                        files = [p for p in sources.rglob("*") if p.is_file()]
                        n_tex_files += len(files)
                        bytes_extracted += sum(p.stat().st_size for p in files)
                    else:
                        n_empty_versions += 1
            refs_path = folder / "references_s2.json"
            if refs_path.exists():
                papers_with_s2_file += 1
                try:
                    records = read_jsonl(refs_path)
                except (OSError, ValueError):
                    records = []
                n_s2_refs += len(records)
                with_arxiv = sum(1 for r in records if r.get("ref_arxiv_id"))
                n_s2_with_arxiv += with_arxiv
                if with_arxiv:
                    papers_with_arxiv_refs += 1

    n_assigned = _assigned_count()
    if n_assigned is None:
        n_assigned = n_resolved

    total_refs_coverage = (papers_with_s2_file / n_resolved) if n_resolved else 0.0
    return {
        "n_assigned": n_assigned,
        "n_resolved": n_resolved,
        "success_rate": round(n_resolved / n_assigned, 4) if n_assigned else 0.0,
        "n_versions": n_versions,
        "n_empty_versions": n_empty_versions,
        "n_tex_versions": n_tex_versions,
        "n_tex_files": n_tex_files,
        "bytes_archives": bytes_archives,
        "bytes_extracted": bytes_extracted,
        "avg_archive_bytes": round(bytes_archives / n_versions, 1) if n_versions else 0.0,
        "avg_extracted_bytes": round(bytes_extracted / n_versions, 1) if n_versions else 0.0,
        "n_s2_refs": n_s2_refs,
        "n_s2_with_arxiv": n_s2_with_arxiv,
        "s2_arxiv_ratio": round(n_s2_with_arxiv / n_s2_refs, 4) if n_s2_refs else 0.0,
        "s2_coverage_rate": round(total_refs_coverage, 4),
        "papers_with_arxiv_refs": papers_with_arxiv_refs,
        "avg_refs_per_paper": round(n_s2_refs / n_resolved, 2) if n_resolved else 0.0,
        "avg_arxiv_refs_per_paper": (round(n_s2_with_arxiv / n_resolved, 2)
                                     if n_resolved else 0.0),
        "working_dir": str(root),
        "disk_working_bytes": directory_size_bytes(str(root)),
    }


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """
    Ghi data/tables/metrics_m1.json để Jupyter Book đọc khi compile.

    Merge lên trên file hiện có (nếu có) để giữ runtime metrics từ track_run.
    """
    from src.common.io import read_json, write_json

    out = Path(path) if path is not None else Path(config.TABLES_DIR) / "metrics_m1.json"
    merged: dict[str, Any] = {}
    if out.exists():
        try:
            existing = read_json(out)
            if isinstance(existing, dict):
                merged.update(existing)
        except (OSError, ValueError):
            pass
    merged.update(payload)
    write_json(out, merged)
    return out
