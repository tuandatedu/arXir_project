"""Validate the two M1 JSON tables: missing information, wrong types, duplicates.

Severity: ``error`` = violates the table schema or integrity (fix before submitting);
``warning`` = legal but information is missing (report it, e.g. a paper without venue).

Run:  python -m src.m1_crawling.validate_tables --tables-dir data/tables
Exit status 1 when there is at least one error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from src.common.ids import normalize_arxiv_id
from src.common.io import read_json, read_jsonl, write_json

PAPER_COLUMNS = ("arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue")
REFERENCE_COLUMNS = ("arxiv_id", "ref_arxiv_id", "ref_title", "ref_authors",
                     "ref_submission_date", "ref_s2_id")

_REF_DATE = re.compile(r"^\d{4}(-\d{2}-\d{2})?$")


def _issue(table: str, row: int, code: str, severity: str, message: str) -> dict:
    return {"table": table, "row": row, "code": code, "severity": severity, "message": message}


def _is_iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value[:10])
    except ValueError:
        return False
    return len(value) == 10 or value[10:11] == "T"


def _canonical_id(value: Any) -> bool:
    """True for a normalized base arXiv ID (no version suffix, URL or prefix)."""
    if not isinstance(value, str) or not value:
        return False
    try:
        return normalize_arxiv_id(value) == value
    except (TypeError, ValueError):
        return False


def _check_columns(table: str, i: int, row: Any, columns: tuple[str, ...]) -> Optional[list[dict]]:
    if not isinstance(row, dict):
        return [_issue(table, i, "not_an_object", "error", "row is not a JSON object")]
    missing, extra = set(columns) - set(row), set(row) - set(columns)
    if missing or extra:
        return [_issue(table, i, "columns", "error",
                       f"missing={sorted(missing)} extra={sorted(extra)}")]
    return None


def _check_str_list(table: str, i: int, field: str, value: Any, *,
                    warn_empty: bool) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        return [_issue(table, i, "type", "error", f"{field} must be list[str], got {type(value).__name__}")]
    if warn_empty and not value:
        return [_issue(table, i, f"missing_{field}", "warning", f"{field} is empty")]
    return []


def validate_papers(rows: list[Any]) -> list[dict]:
    t, issues, seen = "papers", [], Counter()
    for i, row in enumerate(rows):
        bad = _check_columns(t, i, row, PAPER_COLUMNS)
        if bad:
            issues += bad
            continue
        if not _canonical_id(row["arxiv_id"]):
            issues.append(_issue(t, i, "invalid_arxiv_id", "error",
                                 f"arxiv_id {row['arxiv_id']!r} must be a base ID without version"))
        else:
            seen[row["arxiv_id"]] += 1
        if not isinstance(row["title"], str):
            issues.append(_issue(t, i, "type", "error", "title must be str"))
        elif not row["title"].strip():
            issues.append(_issue(t, i, "missing_title", "warning", "title is empty"))
        issues += _check_str_list(t, i, "authors", row["authors"], warn_empty=True)
        sub = row["submission_date"]
        if not isinstance(sub, str):
            issues.append(_issue(t, i, "type", "error", "submission_date must be str"))
        elif not sub:
            issues.append(_issue(t, i, "missing_submission_date", "error", "submission_date is empty"))
        elif not _is_iso_date(sub):
            issues.append(_issue(t, i, "bad_date", "error", f"submission_date {sub!r} is not ISO"))
        revised = _check_str_list(t, i, "revised_dates", row["revised_dates"], warn_empty=False)
        issues += revised
        if not revised:
            for d in row["revised_dates"]:
                if not _is_iso_date(d):
                    issues.append(_issue(t, i, "bad_date", "error", f"revised date {d!r} is not ISO"))
                elif isinstance(sub, str) and _is_iso_date(sub) and d[:10] < sub[:10]:
                    issues.append(_issue(t, i, "revised_before_submission", "warning",
                                         f"revised {d} is earlier than submission {sub}"))
        venue = row["venue"]
        if venue is not None and not isinstance(venue, str):
            issues.append(_issue(t, i, "type", "error", "venue must be str or null"))
        elif venue is not None and not venue.strip():
            issues.append(_issue(t, i, "empty_venue", "warning", "venue is an empty string; use null"))
    for paper_id, count in seen.items():
        if count > 1:
            issues.append(_issue(t, -1, "duplicate_arxiv_id", "error",
                                 f"{paper_id} appears {count} times"))
    return issues


def validate_references(rows: list[Any], paper_ids: Optional[set[str]] = None) -> list[dict]:
    t, issues, seen = "references", [], Counter()
    for i, row in enumerate(rows):
        bad = _check_columns(t, i, row, REFERENCE_COLUMNS)
        if bad:
            issues += bad
            continue
        citing_ok = _canonical_id(row["arxiv_id"])
        cited_ok = _canonical_id(row["ref_arxiv_id"])
        if not citing_ok:
            issues.append(_issue(t, i, "invalid_arxiv_id", "error", f"arxiv_id {row['arxiv_id']!r} invalid"))
        if not cited_ok:
            issues.append(_issue(t, i, "invalid_ref_arxiv_id", "error",
                                 f"ref_arxiv_id {row['ref_arxiv_id']!r} must be non-null and canonical"))
        if citing_ok and cited_ok:
            seen[(row["arxiv_id"], row["ref_arxiv_id"])] += 1
            if row["arxiv_id"] == row["ref_arxiv_id"]:
                issues.append(_issue(t, i, "self_citation", "warning", f"{row['arxiv_id']} cites itself"))
        if citing_ok and paper_ids is not None and row["arxiv_id"] not in paper_ids:
            issues.append(_issue(t, i, "orphan_reference", "error",
                                 f"citing paper {row['arxiv_id']} is not in the papers table"))
        for field in ("ref_title", "ref_s2_id"):
            if not isinstance(row[field], str):
                issues.append(_issue(t, i, "type", "error", f"{field} must be str"))
            elif not row[field].strip():
                issues.append(_issue(t, i, f"missing_{field}", "warning", f"{field} is empty"))
        issues += _check_str_list(t, i, "ref_authors", row["ref_authors"], warn_empty=True)
        date = row["ref_submission_date"]
        if not isinstance(date, str):
            issues.append(_issue(t, i, "type", "error", "ref_submission_date must be str"))
        elif not date:
            issues.append(_issue(t, i, "missing_ref_submission_date", "warning", "ref_submission_date is empty"))
        elif not _REF_DATE.match(date) or (len(date) == 10 and not _is_iso_date(date)):
            issues.append(_issue(t, i, "bad_date", "error", f"ref_submission_date {date!r} is not YYYY or ISO date"))
    for (citing, cited), count in seen.items():
        if count > 1:
            issues.append(_issue(t, -1, "duplicate_reference", "error",
                                 f"({citing} -> {cited}) appears {count} times"))
    return issues


def summarize(issues: Iterable[dict], n_rows: int) -> dict:
    issues = list(issues)
    return {"rows": n_rows,
            "errors": sum(i["severity"] == "error" for i in issues),
            "warnings": sum(i["severity"] == "warning" for i in issues),
            "by_code": dict(Counter(i["code"] for i in issues)),
            "samples": issues[:200]}


def validate_tables(tables_dir: Path, *, verbose: bool = True) -> dict:
    """Validate papers.json/references.json; write validation_report.json."""
    tables_dir = Path(tables_dir)
    def load_table(name: str) -> list[dict]:
        # JSON is the current format; keep JSONL as a fallback for old table folders.
        json_path = tables_dir / f"{name}.json"
        if json_path.is_file():
            rows = read_json(json_path)
            if not isinstance(rows, list):
                raise ValueError(f"{json_path} must contain a JSON array")
            return rows
        return read_jsonl(tables_dir / f"{name}.jsonl")

    papers = load_table("papers")
    references = load_table("references")
    paper_ids = {r["arxiv_id"] for r in papers if isinstance(r.get("arxiv_id"), str)}
    paper_issues = validate_papers(papers)
    reference_issues = validate_references(references, paper_ids)
    report = {"papers": summarize(paper_issues, len(papers)),
              "references": summarize(reference_issues, len(references))}
    report["ok"] = report["papers"]["errors"] == 0 and report["references"]["errors"] == 0
    write_json(tables_dir / "validation_report.json", report)
    if verbose:
        for name in ("papers", "references"):
            part = report[name]
            print(f"[{name}] {part['rows']} dòng | {part['errors']} lỗi | {part['warnings']} cảnh báo")
            for code, count in sorted(part["by_code"].items()):
                print(f"    {code}: {count}")
            for item in part["samples"][:5]:
                print(f"    - [{item['severity']}] dòng {item['row']}: {item['message']}")
        print("KẾT QUẢ:", "HỢP LỆ" if report["ok"] else "CÓ LỖI, xem validation_report.json")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    return 0 if validate_tables(args.tables_dir)["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
