"""
Xuất 2 bảng M1 (schema Hugging Face, cột phẳng).

papers: 1 hàng / publication (không phải / version).
references: 1 hàng / crawled reference CÓ arXiv ID + citing paper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from src.common import config
from src.common.ids import normalize_arxiv_id
from src.common.io import dataclass_to_dict, write_jsonl
from src.common.schemas import PaperRow, ReferenceRow

from .discover import PaperMeta


def paper_meta_to_row(meta: PaperMeta) -> PaperRow:
    """Map PaperMeta → PaperRow (arxiv_id base, không kèm vN)."""
    return PaperRow(
        arxiv_id=normalize_arxiv_id(meta.arxiv_id),
        title=meta.title.strip(),
        authors=[name.strip() for name in meta.authors if name and name.strip()],
        submission_date=meta.submission_date,
        revised_dates=[date for date in meta.revised_dates if date],
        venue=meta.venue.strip() if isinstance(meta.venue, str) and meta.venue.strip() else None,
    )

def dedupe_reference_rows(rows: list[ReferenceRow]) -> list[ReferenceRow]:
    """
    Khử trùng lặp danh sách ReferenceRow dựa trên bộ 3 biến số:
    (arxiv_id, ref_arxiv_id, ref_s2_id).
    
    Đảm bảo đồng bộ với bộ kiểm tra validate_m1_tables.
    """
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ReferenceRow] = []

    for row in rows:
        # Tạo key từ 3 biến số: bài báo gốc, bài báo trích dẫn, và mã Semantic Scholar ID
        key = (
            str(row.arxiv_id or "").strip(),
            str(row.ref_arxiv_id or "").strip(),
            str(row.ref_s2_id or "").strip(),
        )
        
        # Chỉ giữ lại bản ghi đầu tiên xuất hiện
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return deduped

def s2_records_to_reference_rows(
    citing_arxiv_id: str,
    records: list[dict],
) -> list[ReferenceRow]:
    citing = normalize_arxiv_id(citing_arxiv_id)
    rows: list[ReferenceRow] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        ref_arxiv_id = record.get("ref_arxiv_id")
        if not isinstance(ref_arxiv_id, str) or not ref_arxiv_id.strip():
            continue

        ref_arxiv_id = normalize_arxiv_id(ref_arxiv_id)

        date = record.get("ref_submission_date") or ""
        if not date and record.get("year") is not None:
            date = str(record["year"])

        authors = record.get("ref_authors") or []

        rows.append(ReferenceRow(
            arxiv_id=citing,
            ref_arxiv_id=ref_arxiv_id,
            ref_title=(record.get("ref_title") or "").strip(),
            ref_authors=[
                a.strip()
                for a in authors
                if isinstance(a, str) and a.strip()
            ],
            ref_submission_date=str(date),
            ref_s2_id=str(record.get("ref_s2_id") or "").strip(),
        ))

    return dedupe_reference_rows(rows)


def write_m1_tables(papers: list[PaperRow], references: list[ReferenceRow]) -> None:
    """
    Ghi data/tables/papers.json + references.json (mảng JSON, UTF-8).
    Parquet sharded nằm ở bước export HF (M3).
    """
    from src.common.io import write_json

    tables_dir = Path(config.TABLES_DIR)
    write_json(tables_dir / "papers.json",
               [dataclass_to_dict(row) for row in papers])
    write_json(tables_dir / "references.json",
               [dataclass_to_dict(row) for row in references])


# ---------------------------------------------------------------------------
# Kiểm tra chất lượng 2 bảng: thiếu thông tin, sai kiểu dữ liệu, trùng lặp
# ---------------------------------------------------------------------------
_PAPER_COLUMNS = ("arxiv_id", "title", "authors", "submission_date",
                  "revised_dates", "venue")
_REFERENCE_COLUMNS = ("arxiv_id", "ref_arxiv_id", "ref_title", "ref_authors",
                      "ref_submission_date", "ref_s2_id")


def _as_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(dataclass_to_dict(row) if hasattr(row, "__dataclass_fields__")
                   else dict(row))
    return out


def _check_str_list(value: Any, *, nullable: bool = False) -> str | None:
    if value is None:
        return None if nullable else "missing"
    if not isinstance(value, list):
        return f"expected list[str], got {type(value).__name__}"
    if any(not isinstance(item, str) for item in value):
        return "expected list[str], found non-string element"
    return None


def _check_required_str(value: Any) -> str | None:
    if value is None:
        return "missing"
    if not isinstance(value, str):
        return f"expected str, got {type(value).__name__}"
    if not value.strip():
        return "empty"
    return None


def validate_m1_tables(
    papers: list[PaperRow] | list[dict[str, Any]],
    references: list[ReferenceRow] | list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Kiểm tra 2 bảng papers/references trước khi lưu:

    - Thiếu thông tin: field non-null rỗng / None.
    - Sai kiểu dữ liệu: str vs list[str], ngày không phải string.
    - Trùng lặp: papers theo arxiv_id;
      references theo (arxiv_id, ref_arxiv_id, ref_s2_id).

    Trả về {"ok": bool, "issues": [...], "n_papers": int, "n_references": int}.
    """
    paper_rows = _as_dicts(papers)
    reference_rows = _as_dicts(references)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def add(table: str, index: int, field: str, problem: str) -> None:
        issues.append({"table": table, "index": index,
                       "field": field, "problem": problem})

    def warn(table: str, index: int, field: str, problem: str) -> None:
        warnings.append({"table": table, "index": index,
                         "field": field, "problem": problem})

    seen_paper_ids: dict[str, int] = {}
    for index, row in enumerate(paper_rows):
        for column in _PAPER_COLUMNS:
            if column not in row:
                add("papers", index, column, "missing column")
        problem = _check_required_str(row.get("arxiv_id"))
        if problem:
            add("papers", index, "arxiv_id", problem)
        else:
            seen = seen_paper_ids.setdefault(row["arxiv_id"], index)
            if seen != index:
                add("papers", index, "arxiv_id",
                    f"duplicate of row {seen} ({row['arxiv_id']})")
        problem = _check_required_str(row.get("title"))
        if problem:
            add("papers", index, "title", problem)
        problem = _check_str_list(row.get("authors"))
        if problem:
            add("papers", index, "authors", problem)
        elif isinstance(row.get("authors"), list) and not row["authors"]:
            add("papers", index, "authors", "empty")
        problem = _check_required_str(row.get("submission_date"))
        if problem:
            add("papers", index, "submission_date", problem)
        problem = _check_str_list(row.get("revised_dates"), nullable=True)
        if problem:
            add("papers", index, "revised_dates", problem)
        venue = row.get("venue")
        if venue is not None and not isinstance(venue, str):
            add("papers", index, "venue",
                f"expected nullable str, got {type(venue).__name__}")

    seen_reference_keys: dict[tuple[str, str, str], int] = {}
    for index, row in enumerate(reference_rows):
        for column in _REFERENCE_COLUMNS:
            if column not in row:
                add("references", index, column, "missing column")
        for column in ("arxiv_id", "ref_arxiv_id", "ref_title", "ref_s2_id"):
            problem = _check_required_str(row.get(column))
            if problem:
                add("references", index, column, problem)
        problem = _check_required_str(row.get("ref_submission_date"))
        if problem:
            add("references", index, "ref_submission_date", problem)
        problem = _check_str_list(row.get("ref_authors"))
        if problem:
            add("references", index, "ref_authors", problem)
        elif isinstance(row.get("ref_authors"), list) and not row["ref_authors"]:
            # Schema allows list[str]; S2 sometimes omits authors for a
            # reference. Keep the row (and the empty list) instead of
            # fabricating names or dropping the citation.
            warn("references", index, "ref_authors", "empty")
        key = (str(row.get("arxiv_id") or ""),
               str(row.get("ref_arxiv_id") or ""),
               str(row.get("ref_s2_id") or ""))
        if all(key):
            seen = seen_reference_keys.setdefault(key, index)
            if seen != index:
                add("references", index, "arxiv_id",
                    f"duplicate citation of row {seen} ({key[0]} → {key[1]})")

    return {
        "ok": not issues,
        "issues": issues,
        "n_issues": len(issues),
        "warnings": warnings,
        "n_warnings": len(warnings),
        "n_empty_ref_authors": sum(
            1 for warning in warnings
            if warning["table"] == "references"
            and warning["field"] == "ref_authors"
            and warning["problem"] == "empty"),
        "warning_rules": {
            "empty_ref_authors": (
                "allowed: the schema asks for list[str], and S2 may omit "
                "authors for a reference; keep the row and the empty list"),
        },
        "n_papers": len(paper_rows),
        "n_references": len(reference_rows),
    }
