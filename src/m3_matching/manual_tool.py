"""
Công cụ chuẩn bị mẫu gán nhãn thủ công (Task 2) và tổng hợp kết quả của cả nhóm.

Cung cấp:
1. find_candidate_manual_papers: Tìm các bài báo có ≥ 20 BibTeX entries và có references.
2. export_manual_template: Tạo file CSV mẫu dễ nhìn kèm gợi ý thông minh để thành viên nhóm kiểm tra.
3. import_manual_csv: Tổng hợp file CSV nhóm đã kiểm tra vào data/labels/{arxiv_id}.jsonl.
4. summarize_team_labels: Báo cáo tổng kết tiến độ gán nhãn của cả nhóm đối chiếu với quota đề bài.
"""

from __future__ import annotations

import csv
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
from src.m3_matching.labelling import auto_match_one, load_labels, validate_label_quota


def find_candidate_manual_papers(
    bibtex_path: Path | None = None,
    references_path: Path | None = None,
    min_entries: int = 20,
) -> list[tuple[str, int, int]]:
    """
    Tìm danh sách bài báo phù hợp cho việc gán nhãn thủ công:
    - Có ít nhất min_entries BibTeX entries (mặc định ≥ 20)
    - Có crawled references
    Trả về: [(arxiv_id, n_bib_entries, n_refs), ...] sắp xếp giảm dần theo số bib entries.
    """
    bibtex_path = bibtex_path or (TABLES_DIR / "bibtex.jsonl")
    references_path = references_path or (TABLES_DIR / "references.jsonl")

    if not bibtex_path.exists() or not references_path.exists():
        return []

    bib_records = read_jsonl(bibtex_path)
    ref_records = read_jsonl(references_path)

    bib_counts: dict[str, int] = {}
    for b in bib_records:
        pid = b.get("arxiv_id")
        if pid:
            bib_counts[pid] = bib_counts.get(pid, 0) + 1

    ref_counts: dict[str, int] = {}
    for r in ref_records:
        pid = r.get("arxiv_id")
        if pid:
            ref_counts[pid] = ref_counts.get(pid, 0) + 1

    eligible: list[tuple[str, int, int]] = []
    for pid, b_cnt in bib_counts.items():
        r_cnt = ref_counts.get(pid, 0)
        if b_cnt >= min_entries and r_cnt > 0:
            eligible.append((pid, b_cnt, r_cnt))

    eligible.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return eligible


def export_manual_template(
    arxiv_id: str,
    output_csv: Path,
    bibtex_path: Path | None = None,
    references_path: Path | None = None,
) -> Path:
    """
    Xuất file CSV mẫu gán nhãn cho 1 bài báo:
    - Liệt kê mọi BibTeX entry của bài báo
    - Tự động gợi ý candidate có độ tương đồng cao nhất kèm score để người gán nhãn xác nhận nhanh
    - Cột groundtruth_arxiv_id để trống (hoặc điền gợi ý) cho người gán nhãn xác nhận.
    """
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    bibtex_path = bibtex_path or (TABLES_DIR / "bibtex.jsonl")
    references_path = references_path or (TABLES_DIR / "references.jsonl")

    all_bib = read_jsonl(bibtex_path)
    all_refs = read_jsonl(references_path)

    paper_bib = [prepare_bibtex_record(b) for b in all_bib if b.get("arxiv_id") == arxiv_id]
    paper_refs = [prepare_reference_record(r) for r in all_refs if r.get("arxiv_id") == arxiv_id]

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

    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for bib in paper_bib:
            key = bib.get("citation_key") or ""
            # Tìm gợi ý tốt nhất
            best_ref = None
            best_score = 0.0

            for ref in paper_refs:
                ref_id = ref.get("ref_arxiv_id_norm") or ref.get("ref_arxiv_id")
                if not ref_id:
                    continue
                t_sim = title_similarity(bib, ref)
                a_sim = author_overlap(bib, ref)
                y_diff = year_distance(bib, ref)
                score = t_sim * 0.7 + a_sim * 0.2 + (0.1 if (0 <= y_diff <= 1) else 0.0)
                if score > best_score:
                    best_score = score
                    best_ref = ref

            sugg_id = ""
            sugg_title = ""
            if best_ref and best_score >= 0.5:
                sugg_id = best_ref.get("ref_arxiv_id_norm") or best_ref.get("ref_arxiv_id") or ""
                sugg_title = best_ref.get("ref_title") or best_ref.get("title") or ""

            writer.writerow({
                "citation_key": key,
                "bib_title": bib.get("title") or "",
                "bib_authors": "; ".join(bib.get("authors") or []),
                "bib_year": bib.get("year") or "",
                "bib_doi": bib.get("doi") or "",
                "suggested_ref_arxiv_id": sugg_id,
                "suggested_ref_title": sugg_title,
                "suggested_score": f"{best_score:.2f}" if best_score > 0 else "",
                "groundtruth_arxiv_id": sugg_id if best_score >= 0.85 else "",
                "is_verified": "YES" if best_score >= 0.95 else "NO",
                "note": "",
            })

    return output_csv


def import_manual_csv(
    csv_path: Path,
    arxiv_id: str,
    labels_dir: Path | None = None,
) -> Path:
    """
    Đọc file CSV sau khi nhóm đã kiểm tra và lưu vào data/labels/{arxiv_id}.jsonl.
    Mỗi hàng: {"citation_key": key, "groundtruth_arxiv_id": id_or_None, "source": "manual"}
    """
    csv_path = Path(csv_path)
    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = r.get("citation_key", "").strip()
            if not key:
                continue
            gt = r.get("groundtruth_arxiv_id", "").strip()
            # Xử lý null/None/rỗng
            gt_id = gt if gt and gt.lower() not in ("none", "null", "na", "n/a", "-") else None
            rows.append({
                "citation_key": key,
                "groundtruth_arxiv_id": gt_id,
                "source": "manual",
            })

    out_file = labels_dir / f"{arxiv_id}.jsonl"
    write_jsonl(out_file, rows)
    return out_file


def summarize_team_labels(
    labels_dir: Path | None = None,
    n_publications_total: int = 50,
) -> dict[str, Any]:
    """
    Tổng hợp và in báo cáo tiến độ gán nhãn của nhóm so với yêu cầu của thầy.
    """
    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels = load_labels(labels_dir)

    summary: dict[str, Any] = {
        "n_manual_papers": 0,
        "n_manual_entries": 0,
        "manual_details": {},
        "n_auto_papers": 0,
        "n_auto_entries": 0,
        "quota_status": "UNKNOWN",
    }

    for pid, entries in labels.items():
        m_cnt = sum(1 for e in entries if e.get("source") == "manual")
        a_cnt = sum(1 for e in entries if e.get("source") == "auto")
        if m_cnt > 0:
            summary["n_manual_papers"] += 1
            summary["n_manual_entries"] += m_cnt
            summary["manual_details"][pid] = m_cnt
        if a_cnt > 0:
            summary["n_auto_papers"] += 1
            summary["n_auto_entries"] += a_cnt

    try:
        validate_label_quota(labels, n_publications_total)
        summary["quota_status"] = "PASSED"
    except Exception as exc:
        summary["quota_status"] = f"FAILED: {exc}"

    return summary


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Công cụ hỗ trợ gán nhãn thủ công (Milestone 3)")
    parser.add_argument("--find-candidates", action="store_true", help="Tìm các bài báo đủ điều kiện gán nhãn thủ công (≥ 20 bib entries)")
    parser.add_argument("--export-template", type=str, help="Xuất file CSV mẫu cho 1 bài báo (ví dụ --export-template 2310.12345)")
    parser.add_argument("--import-csv", type=str, help="Import file CSV đã kiểm tra vào data/labels (ví dụ --import-csv path/to/file.csv)")
    parser.add_argument("--paper-id", type=str, help="arXiv ID khi import CSV (nếu tên file không trùng ID)")
    parser.add_argument("--summary", action="store_true", help="Tổng hợp tiến độ gán nhãn của cả nhóm")
    args = parser.parse_args()

    if args.find_candidates:
        candidates = find_candidate_manual_papers()
        print(f"Tìm thấy {len(candidates)} bài báo có ≥ 20 BibTeX entries và có references:")
        for pid, b_cnt, r_cnt in candidates[:15]:
            print(f"  - {pid}: {b_cnt} BibTeX entries | {r_cnt} References")

    elif args.export_template:
        pid = args.export_template
        out_csv = DATA_DIR / "labels" / "manual_templates" / f"{pid}.csv"
        export_manual_template(pid, out_csv)
        print(f"Đã xuất template gán nhãn cho {pid} tại: {out_csv}")

    elif args.import_csv:
        csv_file = Path(args.import_csv)
        pid = args.paper_id or csv_file.stem
        out_jsonl = import_manual_csv(csv_file, pid)
        print(f"Đã import nhãn thủ công cho {pid} vào: {out_jsonl}")

    elif args.summary:
        res = summarize_team_labels()
        print("=== BÁO CÁO TIẾN ĐỘ GÁN NHÃN ===")
        print(f"Số bài manual: {res['n_manual_papers']} (yêu cầu ≥ 5)")
        print(f"Tổng entries manual: {res['n_manual_entries']} (yêu cầu ≥ 100)")
        print(f"Chi tiết manual: {res['manual_details']}")
        print(f"Số bài auto: {res['n_auto_papers']}")
        print(f"Trạng thái hạn mức (Quota): {res['quota_status']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

