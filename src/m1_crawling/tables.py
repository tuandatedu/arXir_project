"""Convert M1 metadata into the two flat dataset tables."""
from __future__ import annotations

from pathlib import Path

from src.common.config import TABLES_DIR
from src.common.ids import normalize_arxiv_id
from src.common.io import dataclass_to_dict, write_json, write_jsonl
from src.common.schemas import PaperRow, ReferenceRow
from .discover import PaperMeta


def paper_meta_to_row(meta: PaperMeta) -> PaperRow:
    """Map one publication's discovery metadata to its single papers row."""
    # One row represents the publication; versions are described in revised_dates.
    return PaperRow(
        arxiv_id=normalize_arxiv_id(meta.arxiv_id), title=meta.title,
        authors=list(meta.authors), submission_date=meta.submission_date,
        revised_dates=list(meta.revised_dates), venue=meta.venue,
    )


def ref_row_from_record(citing_arxiv_id: str, record: dict) -> ReferenceRow | None:
    """Flatten one local S2 record; return None when either ID is unusable.

    Semantic Scholar occasionally returns malformed ``externalIds.ArXiv`` values
    (kept verbatim by semantic_scholar.py); one bad reference must never abort
    the table build, so such rows are dropped and counted by callers.
    """
    ref_id = record.get("ref_arxiv_id")
    if not ref_id:
        return None
    try:
        citing = normalize_arxiv_id(citing_arxiv_id)
        ref = normalize_arxiv_id(str(ref_id))
    except (TypeError, ValueError):
        return None
    return ReferenceRow(
        arxiv_id=citing,
        ref_arxiv_id=ref,
        ref_title=str(record.get("ref_title") or ""),
        ref_authors=list(record.get("ref_authors") or []),
        ref_submission_date=str(record.get("ref_submission_date") or ""),
        ref_s2_id=str(record.get("ref_s2_id") or ""),
    )


def s2_records_to_reference_rows(citing_arxiv_id: str,
                                 records: list[dict]) -> list[ReferenceRow]:
    """Keep only references with a valid arXiv ID for the published table."""
    # The local JSON keeps all references; the published table requires an arXiv ID.
    rows = []
    for record in records:
        row = ref_row_from_record(citing_arxiv_id, record)
        if row is not None:
            rows.append(row)
    return rows


def write_m1_tables(papers: list[PaperRow], references: list[ReferenceRow],
                    tables_dir: Path | None = None) -> None:
    """Write UTF-8 JSONL working tables in schema field order."""
    # Use the default project data folder, or a Drive folder in Colab.
    output_dir = Path(tables_dir) if tables_dir is not None else TABLES_DIR
    # Convert typed rows to plain dictionaries before serializing to JSONL.
    paper_rows = [dataclass_to_dict(row) for row in papers]
    reference_rows = [dataclass_to_dict(row) for row in references]
    # Write one JSON array per table for convenient inspection and sharing.
    write_json(output_dir / "papers.json", paper_rows)
    write_json(output_dir / "references.json", reference_rows)
    # Keep JSONL outputs for existing downstream tools that stream rows.
    write_jsonl(output_dir / "papers.jsonl", paper_rows)
    write_jsonl(output_dir / "references.jsonl", reference_rows)
