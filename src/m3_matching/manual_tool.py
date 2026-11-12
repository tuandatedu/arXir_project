
"""
Công cụ gán nhãn thủ công và tổng hợp kết quả M3.

- BibTeX: đọc bibtex.jsonl trực tiếp bên trong M2 ZIP.
- References: đọc references.json.
- Manual templates: lưu tại data/labels/manual/{arxiv_id}.csv.
- Manual labels: lưu tại data/labels/{arxiv_id}.jsonl.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import zipfile

from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR, TABLES_DIR
from src.common.io import read_jsonl, write_jsonl

from src.m3_matching.cleaning import (
    prepare_bibtex_record,
    prepare_reference_record,
)

from src.m3_matching.features import (
    author_overlap,
    title_similarity,
    year_distance,
)

from src.m3_matching.labelling import (
    load_labels,
    validate_label_quota,
)


# ============================================================
# 1. ĐỌC DỮ LIỆU
# ============================================================

def load_json_records(path: Path) -> list[dict[str, Any]]:
    """Đọc JSON hoặc JSONL thành danh sách records."""

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)

    if path.suffix.lower() != ".json":
        raise ValueError(f"Định dạng không hỗ trợ: {path.suffix}")

    content = path.read_text(encoding="utf-8-sig").strip()

    if not content:
        return []

    # Thử đọc JSON thông thường
    try:
        data = json.loads(content)

    except json.JSONDecodeError:
        # Nếu thực tế là JSONL nhưng mang đuôi .json
        records = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON lỗi tại dòng {line_no} trong {path}"
                ) from exc

        return records

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "records", "items"):
            if isinstance(data.get(key), list):
                return data[key]

        return [data]

    raise ValueError(f"Cấu trúc JSON không hợp lệ: {path}")


def load_bibtex_records(path: Path) -> list[dict[str, Any]]:
    """
    Đọc BibTeX từ:
    - .jsonl trực tiếp
    - .zip chứa bibtex.jsonl
    - .json
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy BibTeX: {path}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as archive:
            members = [
                name for name in archive.namelist()
                if Path(name).name.lower() == "bibtex.jsonl"
            ]

            if not members:
                raise FileNotFoundError(
                    f"Không tìm thấy bibtex.jsonl bên trong {path.name}"
                )

            if len(members) > 1:
                raise ValueError(
                    "ZIP chứa nhiều file bibtex.jsonl:\n"
                    + "\n".join(members)
                    + "\nHãy chỉ rõ file cần đọc."
                )

            with archive.open(members[0], "r") as file:
                text = io.TextIOWrapper(
                    file,
                    encoding="utf-8-sig",
                )
                return [
                    json.loads(line)
                    for line in text
                    if line.strip()
                ]

    return load_json_records(path)


def load_reference_records(path: Path) -> list[dict[str, Any]]:
    """References được đọc trực tiếp từ references.json."""

    return load_json_records(path)


# ============================================================
# 2. TÌM PUBLICATION ĐỦ ĐIỀU KIỆN MANUAL
# ============================================================

def find_candidate_manual_papers(
    bibtex_path: Path,
    references_path: Path,
    min_entries: int = 20,
) -> list[tuple[str, int, int]]:

    bib_records = load_bibtex_records(bibtex_path)
    ref_records = load_reference_records(references_path)

    bib_counts: dict[str, int] = {}
    for record in bib_records:
        pid = record.get("arxiv_id")
        if pid:
            bib_counts[pid] = bib_counts.get(pid, 0) + 1

    ref_counts: dict[str, int] = {}
    for record in ref_records:
        pid = record.get("arxiv_id")
        if pid:
            ref_counts[pid] = ref_counts.get(pid, 0) + 1

    eligible = []

    for pid, bib_count in bib_counts.items():
        ref_count = ref_counts.get(pid, 0)

        if bib_count >= min_entries and ref_count > 0:
            eligible.append((pid, bib_count, ref_count))

    eligible.sort(
        key=lambda item: (item[1], item[2]),
        reverse=True,
    )

    return eligible


# ============================================================
# 3. XUẤT MANUAL TEMPLATE
# ============================================================

def export_manual_template(
    arxiv_id: str,
    output_csv: Path,
    bibtex_path: Path,
    references_path: Path,
) -> Path:

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    all_bib = load_bibtex_records(bibtex_path)
    all_refs = load_reference_records(references_path)

    paper_bib = [
        prepare_bibtex_record(record)
        for record in all_bib
        if record.get("arxiv_id") == arxiv_id
    ]

    paper_refs = [
        prepare_reference_record(record)
        for record in all_refs
        if record.get("arxiv_id") == arxiv_id
    ]

    if not paper_bib:
        raise ValueError(f"Không tìm thấy BibTeX của {arxiv_id}")

    if not paper_refs:
        raise ValueError(f"Không tìm thấy References của {arxiv_id}")

    fieldnames = [
        "citation_key",
        "bib_title",
        "bib_authors",
        "bib_year",
        "bib_doi",
        "suggested_ref_arxiv_id",
        "suggested_ref_title",
        "suggested_score",
        "groundtruth_arxiv_id",
        "is_verified",
        "note",
    ]

    with output_csv.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for bib in paper_bib:
            best_ref = None
            best_score = 0.0

            for ref in paper_refs:
                ref_id = (
                    ref.get("ref_arxiv_id_norm")
                    or ref.get("ref_arxiv_id")
                )

                if not ref_id:
                    continue

                t_sim = title_similarity(bib, ref)
                a_sim = author_overlap(bib, ref)
                y_diff = year_distance(bib, ref)

                score = (
                    t_sim * 0.7
                    + a_sim * 0.2
                    + (0.1 if 0 <= y_diff <= 1 else 0.0)
                )

                if score > best_score:
                    best_score = score
                    best_ref = ref

            suggested_id = ""
            suggested_title = ""

            if best_ref and best_score >= 0.5:
                suggested_id = (
                    best_ref.get("ref_arxiv_id_norm")
                    or best_ref.get("ref_arxiv_id")
                    or ""
                )

                suggested_title = (
                    best_ref.get("ref_title")
                    or best_ref.get("title")
                    or ""
                )

            writer.writerow({
                "citation_key": bib.get("citation_key") or "",
                "bib_title": bib.get("title") or "",
                "bib_authors": "; ".join(bib.get("authors") or []),
                "bib_year": bib.get("year") or "",
                "bib_doi": bib.get("doi") or "",
                "suggested_ref_arxiv_id": suggested_id,
                "suggested_ref_title": suggested_title,
                "suggested_score": (
                    f"{best_score:.2f}" if best_score > 0 else ""
                ),

                # Groundtruth phải được con người xác nhận.
                "groundtruth_arxiv_id": "",
                "is_verified": "NO",
                "note": "",
            })

    return output_csv


# ============================================================
# 4. IMPORT MANUAL LABELS
# ============================================================

def import_manual_csv(
    csv_path: Path,
    arxiv_id: str,
    labels_dir: Path | None = None,
    *,
    require_verified: bool = True,
) -> Path:
    """
    Import manual CSV → JSONL for groundtruth labels.
    
    Workflow:
    1. User fills groundtruth_arxiv_id (manual) OR ticks is_verified=YES
    2. If is_verified=YES, auto-fill groundtruth_arxiv_id = suggested_ref_arxiv_id
    3. Code creates JSONL with citation_key + groundtruth_arxiv_id + source
    """

    csv_path = Path(csv_path)

    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    skipped_unverified = 0

    with csv_path.open("r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        has_verified = "is_verified" in (reader.fieldnames or [])

        for record in reader:
            key = (record.get("citation_key") or "").strip()

            if not key:
                continue

            verified = (
                record.get("is_verified") or ""
            ).strip().upper()

            if require_verified and has_verified and verified != "YES":
                skipped_unverified += 1
                continue

            # Priority 1: explicit groundtruth_arxiv_id from user
            gt = (
                record.get("groundtruth_arxiv_id") or ""
            ).strip()

            gt_id = (
                gt
                if gt and gt.lower() not in (
                    "none", "null", "na", "n/a", "-"
                )
                else None
            )

            # Priority 2: if is_verified=YES but no groundtruth, auto-fill from suggested
            if not gt_id and verified == "YES":
                suggested = (
                    record.get("suggested_ref_arxiv_id") or ""
                ).strip()

                gt_id = (
                    suggested
                    if suggested and suggested.lower() not in (
                        "none", "null", "na", "n/a", "-", ""
                    )
                    else None
                )

            if gt_id:
                rows.append({
                    "citation_key": key,
                    "groundtruth_arxiv_id": gt_id,
                    "source": "manual",
                })

    if not rows:
        raise ValueError(
            f"Không có nhãn hợp lệ trong {csv_path.name}. "
            "Hãy kiểm tra và đánh dấu is_verified=YES hoặc điền groundtruth_arxiv_id."
        )

    if skipped_unverified:
        print(
            f"[WARN] Bỏ qua {skipped_unverified} dòng chưa xác nhận."
        )

    output = labels_dir / f"{arxiv_id}.jsonl"
    write_jsonl(output, rows)

    return output


# ============================================================
# 5. TỔNG HỢP TIẾN ĐỘ GÁN NHÃN
# ============================================================

def summarize_team_labels(
    labels_dir: Path | None = None,
    n_publications_total: int = 50,
    k: int = 1,
) -> dict[str, Any]:

    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels = load_labels(labels_dir)

    summary = {
        "n_manual_papers": 0,
        "n_manual_entries": 0,
        "manual_details": {},
        "n_auto_papers": 0,
        "n_auto_entries": 0,
        "quota_status": "UNKNOWN",
        "k": k,
    }

    for pid, entries in labels.items():
        manual_count = sum(
            1 for entry in entries
            if entry.get("source") == "manual"
        )

        auto_count = sum(
            1 for entry in entries
            if entry.get("source") == "auto"
        )

        if manual_count:
            summary["n_manual_papers"] += 1
            summary["n_manual_entries"] += manual_count
            summary["manual_details"][pid] = manual_count

        if auto_count:
            summary["n_auto_papers"] += 1
            summary["n_auto_entries"] += auto_count

    try:
        validate_label_quota(
            labels,
            n_publications_total,
            k=k,
        )
        summary["quota_status"] = "PASSED"

    except Exception as exc:
        summary["quota_status"] = f"FAILED: {exc}"

    return summary


# ============================================================
# 6. COMMAND LINE
# ============================================================

def main() -> None:

    import argparse

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="M3 Manual Labeling Tool"
    )

    parser.add_argument("--find-candidates", action="store_true")
    parser.add_argument("--export-template", type=str)
    parser.add_argument("--import-csv", type=str)
    parser.add_argument("--paper-id", type=str)
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--summary", action="store_true")

    parser.add_argument(
        "--bibtex-path",
        type=Path,
        help="Đường dẫn ZIP chứa bibtex.jsonl hoặc file JSONL",
    )

    parser.add_argument(
        "--references-path",
        type=Path,
        help="Đường dẫn references.json",
    )

    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--n-publications", type=int, default=50)

    args = parser.parse_args()

    if args.find_candidates or args.export_template:
        if not args.bibtex_path or not args.references_path:
            parser.error(
                "Cần cung cấp --bibtex-path và --references-path."
            )

    if args.find_candidates:
        candidates = find_candidate_manual_papers(
            args.bibtex_path,
            args.references_path,
        )

        print(f"Tìm thấy {len(candidates)} bài đủ điều kiện:")

        for pid, bib_count, ref_count in candidates[:15]:
            print(
                f"- {pid}: {bib_count} BibTeX | "
                f"{ref_count} References"
            )

    elif args.export_template:
        pid = args.export_template

        output = (
            DATA_DIR / "labels" / "manual" / f"{pid}.csv"
        )

        export_manual_template(
            pid,
            output,
            args.bibtex_path,
            args.references_path,
        )

        print(f"Đã xuất CSV: {output}")

    elif args.import_csv:
        csv_path = Path(args.import_csv)
        pid = args.paper_id or csv_path.stem

        output = import_manual_csv(
            csv_path,
            pid,
            require_verified=not args.allow_unverified,
        )

        print(f"Đã import labels: {output}")

    elif args.summary:
        result = summarize_team_labels(
            n_publications_total=args.n_publications,
            k=args.k,
        )

        print("=== BÁO CÁO GÁN NHÃN ===")
        print(f"Manual papers: {result['n_manual_papers']}")
        print(f"Manual entries: {result['n_manual_entries']}")
        print(f"Manual details: {result['manual_details']}")
        print(f"Auto papers: {result['n_auto_papers']}")
        print(f"Auto entries: {result['n_auto_entries']}")
        print(f"Quota: {result['quota_status']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
