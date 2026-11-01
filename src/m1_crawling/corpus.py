"""
Layout working corpus M1 (gợi ý đề, nhóm được phép chỉnh nếu ghi README).

data/working/{folder_id}/
  paper.json                 # metadata publication (title, authors, dates, venue)
  references_s2.json         # MỌI crawled reference (kể cả không có arXiv ID)
  v1/
    metadata.json            # metadata riêng version (nếu khác latest)
    sources/                 # chỉ .tex / .bib đã extract
  v2/
    ...
  empty_vN.json              # version PDF-only / không TeX: empty record, KHÔNG drop paper
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from src.common import config
from src.common.ids import folder_name_for_arxiv_id, normalize_arxiv_id
from src.common.io import write_json

from .discover import PaperMeta


def publication_dir(arxiv_id: str) -> Path:
    """data/working/{folder_name_for_arxiv_id}."""
    return Path(config.WORKING_DIR) / folder_name_for_arxiv_id(arxiv_id)


def version_source_dir(arxiv_id: str, version: int) -> Path:
    """data/working/{id}/v{N}/sources/."""
    if not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    return publication_dir(arxiv_id) / f"v{version}" / "sources"


def save_paper_meta(arxiv_id: str, meta: PaperMeta) -> Path:
    """Ghi paper.json (title, authors, submission_date, revised_dates, venue, versions)."""
    base = normalize_arxiv_id(arxiv_id)
    payload = {
        "arxiv_id": base,
        "title": meta.title,
        "authors": list(meta.authors),
        "abstract": meta.abstract,
        "submission_date": meta.submission_date,
        "revised_dates": list(meta.revised_dates),
        "venue": meta.venue,
        "categories": list(meta.categories),
        "latest_version": meta.latest_version,
        "versions": list(range(1, meta.latest_version + 1)),
    }
    path = publication_dir(base) / "paper.json"
    write_json(path, payload)
    return path


def save_version_sources(
    arxiv_id: str,
    version: int,
    extracted_files: list[Path],
    *,
    empty: bool,
    reason: str = "",
) -> None:
    """
    Copy/ghi sources vào vN/sources, hoặc ghi empty record nếu empty=True.

    - empty=True: KHÔNG xóa publication; ghi marker (empty.json) + reason
      (pdf-only, no tex, 404).
    - empty=False: giữ relative path, không sửa nội dung TeX.
    """
    base = normalize_arxiv_id(arxiv_id)
    version_dir = publication_dir(base) / f"v{version}"
    version_dir.mkdir(parents=True, exist_ok=True)
    if empty:
        write_json(version_dir / "empty.json", {
            "empty": True,
            "version": version,
            "reason": reason or "no tex/bib extracted",
        })
        return
    sources_dir = version_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    for file_path in extracted_files:
        file_path = Path(file_path)
        if not file_path.is_file():
            continue
        try:
            relative = file_path.resolve().relative_to(sources_dir.resolve())
            destination = sources_dir / relative
        except ValueError:
            destination = sources_dir / file_path.name
        if file_path.resolve() == destination.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file_path), str(destination))


def save_s2_references(arxiv_id: str, records: list[dict[str, Any]]) -> Path:
    """Ghi references_s2.json (toàn bộ S2 refs của publication, kể cả không có arXiv ID)."""
    from src.common.io import write_jsonl

    base = normalize_arxiv_id(arxiv_id)
    path = publication_dir(base) / "references_s2.json"
    write_jsonl(path, records)
    return path


def iter_publications(working_dir: Path | None = None) -> list[str]:
    """Liệt kê arxiv_id đã crawl (để M2 đọc lại, không crawl lần nữa)."""
    root = Path(working_dir) if working_dir is not None else Path(config.WORKING_DIR)
    if not root.is_dir():
        return []
    ids: list[str] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        paper_json = folder / "paper.json"
        if paper_json.exists():
            import json
            try:
                payload = json.loads(paper_json.read_text(encoding="utf-8"))
                ids.append(str(payload["arxiv_id"]))
                continue
            except (ValueError, KeyError, OSError):
                pass
        # Fallback khi thiếu paper.json: suy từ tên folder.
        name = folder.name
        if "_" in name:
            ids.append(name.replace("_", "/", 1))
        elif "-" in name:
            ids.append(name.replace("-", ".", 1))
    return ids
