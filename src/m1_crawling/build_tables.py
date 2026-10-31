"""Build the two M1 tables (papers, references) from batch checkpoints + reference folders.

Inputs under ``data_dir``:
  batch_*.tar.gz (+ batch_*.json)   -> member ``papers.jsonl`` (one row per resolved paper)
  reference_*/{id}.json             -> every Semantic Scholar reference of that paper

Outputs under ``tables_dir`` (default ``data_dir/tables``):
  papers.json, references.json      -> JSON arrays matching PaperRow / ReferenceRow
  build_report.json                 -> counts of everything that was skipped or removed

Only references that carry a valid arXiv ID reach the references table; the full reference
lists stay in reference_*/. Nothing here raises on a single bad record: it is counted.
"""
from __future__ import annotations

import json
import logging
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from src.common.ids import normalize_arxiv_id
from src.common.io import write_json
from src.common.schemas import PaperRow, ReferenceRow
from .tables import ref_row_from_record, write_m1_tables

LOG = logging.getLogger(__name__)


def _string_list(value: Any) -> list[str]:
    """Coerce to list[str] without exploding a bare string into characters."""
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value:
        return [value]
    return []


def _read_member_jsonl(archive: Path, member_name: str) -> list[dict]:
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            if member.name == member_name:
                handle = tf.extractfile(member)
                return [json.loads(line) for line in handle if line.strip()] if handle else []
    raise ValueError(f"{member_name} missing in {archive}")


def collect_papers(data_dir: Path, *, batch_names: Optional[Iterable[str]] = None
                   ) -> tuple[list[PaperRow], dict]:
    rows: list[PaperRow] = []
    seen: set[str] = set()
    wanted_batches = set(batch_names) if batch_names is not None else None
    stats: dict[str, Any] = {"batches_read": 0, "batches_skipped_invalid": [],
                             "paper_rows_read": 0, "papers_invalid_id": 0,
                             "papers_duplicates_removed": 0}
    for marker in sorted(Path(data_dir).glob("batch_*.json")):
        if wanted_batches is not None and marker.stem not in wanted_batches:
            continue
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        archive = marker.with_suffix(".tar.gz")
        if not archive.is_file() or archive.stat().st_size != manifest.get("archive_bytes"):
            stats["batches_skipped_invalid"].append(marker.name)
            continue
        stats["batches_read"] += 1
        for raw in _read_member_jsonl(archive, "papers.jsonl"):
            stats["paper_rows_read"] += 1
            try:
                paper_id = normalize_arxiv_id(raw["arxiv_id"])
            except (KeyError, TypeError, ValueError):
                stats["papers_invalid_id"] += 1
                continue
            if paper_id in seen:
                stats["papers_duplicates_removed"] += 1
                continue
            seen.add(paper_id)
            rows.append(PaperRow(
                arxiv_id=paper_id,
                title=str(raw.get("title") or ""),
                authors=_string_list(raw.get("authors")),
                submission_date=str(raw.get("submission_date") or ""),
                revised_dates=_string_list(raw.get("revised_dates")),
                venue=(str(raw["venue"]) if raw.get("venue") else None),
            ))
    rows.sort(key=lambda row: row.arxiv_id)
    return rows, stats


def collect_references(data_dir: Path, paper_ids: set[str], *,
                       batch_names: Optional[Iterable[str]] = None
                       ) -> tuple[list[ReferenceRow], dict]:
    rows: list[ReferenceRow] = []
    wanted_reference_dirs = (
        {"reference_" + name.removeprefix("batch_") for name in batch_names}
        if batch_names is not None else None
    )
    seen: set[tuple[str, str]] = set()
    file_status: Counter = Counter()
    stats: dict[str, Any] = {"reference_files": 0, "reference_files_unreadable": [],
                             "reference_files_orphan": 0, "references_total": 0,
                             "references_with_arxiv_id": 0, "references_invalid_arxiv_id": 0,
                             "references_duplicates_removed": 0}
    papers_with_file: set[str] = set()
    for ref_dir in sorted(p for p in Path(data_dir).glob("reference_*") if p.is_dir()):
        if wanted_reference_dirs is not None and ref_dir.name not in wanted_reference_dirs:
            continue
        for path in sorted(ref_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"))
                citing = normalize_arxiv_id(record["arxiv_id"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                stats["reference_files_unreadable"].append(f"{ref_dir.name}/{path.name}")
                continue
            stats["reference_files"] += 1
            file_status[str(record.get("status"))] += 1
            if citing not in paper_ids:
                stats["reference_files_orphan"] += 1
                continue
            if record.get("status") in ("ok", "empty"):
                papers_with_file.add(citing)
            for item in record.get("references") or []:
                if not isinstance(item, dict):
                    continue
                stats["references_total"] += 1
                if not item.get("ref_arxiv_id"):
                    continue
                stats["references_with_arxiv_id"] += 1
                row = ref_row_from_record(citing, item)
                if row is None:
                    stats["references_invalid_arxiv_id"] += 1
                    continue
                key = (row.arxiv_id, row.ref_arxiv_id)
                if key in seen:
                    stats["references_duplicates_removed"] += 1
                    continue
                seen.add(key)
                rows.append(row)
    rows.sort(key=lambda row: (row.arxiv_id, row.ref_arxiv_id))
    stats["reference_files_by_status"] = dict(file_status)
    stats["papers_without_reference_data"] = sorted(paper_ids - papers_with_file)
    return rows, stats


def build_tables(data_dir: Path, tables_dir: Optional[Path] = None, *,
                 batch_names: Optional[Iterable[str]] = None) -> dict:
    """Write papers.json, references.json and build_report.json; return the report."""
    data_dir = Path(data_dir)
    tables_dir = Path(tables_dir) if tables_dir is not None else data_dir / "tables"
    wanted_batches = set(batch_names) if batch_names is not None else None
    papers, paper_stats = collect_papers(data_dir, batch_names=wanted_batches)
    if paper_stats["batches_read"] and not papers:
        raise RuntimeError(
            "No paper rows were found in valid batch archives. "
            "The batches may have failed during arXiv discovery; rerun the crawler "
            "to retry those checkpoints before building tables."
        )
    references, reference_stats = collect_references(
        data_dir, {p.arxiv_id for p in papers}, batch_names=wanted_batches
    )
    write_m1_tables(papers, references, tables_dir=tables_dir)
    report = {"tables_dir": str(tables_dir), "papers_rows": len(papers),
              "references_rows": len(references),
              "papers": paper_stats, "references": reference_stats}
    write_json(tables_dir / "build_report.json", report)
    return report


def build_batch_tables(data_dir: Path, batch_name: str) -> dict:
    """Write one batch's tables under its matching ``reference_XXXXX/tables`` folder."""
    data_dir = Path(data_dir)
    if not batch_name.startswith("batch_"):
        raise ValueError("batch_name must look like 'batch_00000'")
    suffix = batch_name.removeprefix("batch_")
    tables_dir = data_dir / f"reference_{suffix}" / "tables"
    return build_tables(data_dir, tables_dir=tables_dir, batch_names=[batch_name])
