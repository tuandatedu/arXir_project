"""
Script thực thi trọn gói: Chuẩn bị dữ liệu cho Milestone 3.

Thực hiện toàn bộ 6 bước:
1. Đọc và chuẩn hóa dữ liệu từ bibtex.json và references.json (hoặc .jsonl).
2. Kiểm tra các nhãn thủ công (data/labels/manual/*.json) của nhóm.
3. Chạy gán nhãn tự động cho ≥ 10% các bài báo còn lại (ngoài nhóm manual).
4. Kiểm tra toàn bộ hạn mức (quota) theo quy định của thầy.
5. Chia tập train / valid / test theo publication (hỗ trợ nhóm k thành viên).
6. Tạo ma trận cặp ứng viên kèm 14 đặc trưng và nhãn 0/1, xuất ra Parquet.

Cách dùng:
  python -m src.m3_matching.prepare_dataset
  python -m src.m3_matching.prepare_dataset --k 2 --seed 42
  python -m src.m3_matching.prepare_dataset --demo  (nếu chưa có dữ liệu M1/M2)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zipfile
from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR, TABLES_DIR
from src.common.io import read_json, read_jsonl, write_json
from src.m3_matching.dataset import generate_training_dataset
from src.m3_matching.features import feature_names
from src.m3_matching.labelling import (
    auto_label_publication,
    load_labels,
    save_labels,
    validate_label_quota,
)
from src.m3_matching.split import split_publications
from src.common.ids import normalize_arxiv_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger(__name__)

# Chỉ các trạng thái này mới chứng minh query không có candidate đúng.
_NO_MATCH_STATUSES = {"no_match", "confirmed_no_match", "negative"}


def _normalize_optional_id(value: Any) -> str | None:
    """Chuẩn hóa arXiv ID tùy chọn để so khớp GT với candidate pool."""
    if value is None or not str(value).strip():
        return None
    try:
        return normalize_arxiv_id(str(value))
    except ValueError:
        return str(value).strip()


def _empty_query_bucket() -> dict[str, int]:
    """Một nhóm thống kê query, các nhóm con loại trừ nhau."""
    return {
        "total": 0,
        "match": 0,
        "no_match": 0,
        "unknown": 0,
        "gt_outside_candidate_pool": 0,
        "queries_with_pairs": 0,
        "queries_without_pairs": 0,
    }


def _sum_query_buckets(buckets: list[dict[str, int]]) -> dict[str, int]:
    total = _empty_query_bucket()
    for bucket in buckets:
        for name in total:
            total[name] += int(bucket.get(name, 0))
    return total


def build_query_stats(
    labels: dict[str, list[dict[str, Any]]],
    partition_map: dict[str, str],
    refs_by_paper: dict[str, list[dict[str, Any]]],
    pair_query_keys: set[tuple[str, str]],
) -> tuple[dict[str, dict[str, dict[str, int]]], list[dict[str, Any]]]:
    """
    Thống kê query theo source (manual/automatic) và partition.

    ``match``, ``no_match``, ``unknown``, ``gt_outside_candidate_pool`` là bốn
    nhóm loại trừ nhau. ``gt_outside_candidate_pool`` KHÔNG cộng vào ``match``
    để Candidate Coverage có thể tính riêng.
    """
    breakdown: dict[str, dict[str, dict[str, int]]] = {}
    gt_outside: list[dict[str, Any]] = []

    for pid, rows in labels.items():
        available_ids = {
            _normalize_optional_id(r.get("ref_arxiv_id"))
            for r in refs_by_paper.get(pid, [])
        }
        available_ids.discard(None)
        source = (
            "manual"
            if any(str(r.get("source", "")).lower() == "manual" for r in rows)
            else "automatic"
        )
        partition = partition_map.get(pid, "unassigned")
        bucket = breakdown.setdefault(source, {}).setdefault(
            partition, _empty_query_bucket()
        )

        for row in rows:
            gt = _normalize_optional_id(row.get("groundtruth_arxiv_id"))
            status = str(
                row.get("label_status")
                or row.get("review_status")
                or ("match" if gt else "unknown")
            ).lower()
            key = (str(pid), str(row.get("citation_key") or "").strip())
            has_pairs = key in pair_query_keys

            bucket["total"] += 1
            bucket["queries_with_pairs" if has_pairs else "queries_without_pairs"] += 1

            if gt and gt not in available_ids:
                bucket["gt_outside_candidate_pool"] += 1
                gt_outside.append({
                    "arxiv_id": pid,
                    "citation_key": row.get("citation_key"),
                    "groundtruth_arxiv_id": gt,
                    "source": source,
                    "partition": partition,
                })
            elif gt:
                bucket["match"] += 1
            elif status in _NO_MATCH_STATUSES:
                bucket["no_match"] += 1
            else:
                # Auto null và Manual blank chưa xác nhận đều là unknown.
                bucket["unknown"] += 1

    return breakdown, gt_outside


def _configure_utf8_stdout() -> None:
    """Windows console mặc định cp1258 không in được tiếng Việt; ép UTF-8 khi có thể."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover - môi trường không hỗ trợ
            pass


def create_demo_data_if_missing(tables_dir: Path, labels_dir: Path, k: int = 1) -> None:
    """Tạo dữ liệu mẫu phục vụ test thử nghiệm nếu chưa có dữ liệu crawl M1/M2."""
    tables_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    bib_file = tables_dir / "bibtex.json"
    ref_file = tables_dir / "references.json"

    if bib_file.exists() and ref_file.exists():
        return

    LOG.info("Chưa có data/tables/bibtex.json. Đang khởi tạo dữ liệu mẫu (demo) để kiểm thử...")

    bib_rows = []
    ref_rows = []

    # Tạo tối thiểu 5*k bài manual + 5 bài auto
    n_manual = 5 * k
    n_auto = 4 * k
    total_papers = n_manual + n_auto

    for p_idx in range(1, total_papers + 1):
        pid = f"2401.{p_idx:05d}"
        is_manual = p_idx <= n_manual
        n_entries = 22 if is_manual else 15

        # Tạo bib entries
        for e_idx in range(1, n_entries + 1):
            ckey = f"cite_{p_idx}_{e_idx}"
            title = f"Research on Artificial Intelligence Method {e_idx} for Paper {p_idx}"
            year = 2018 + (e_idx % 6)
            bib_rows.append({
                "arxiv_id": pid,
                "citation_key": ckey,
                "entry_type": "article",
                "title": title,
                "authors": [f"Nguyen, A.", f"Tran, B."],
                "year": year,
                "doi": f"10.1000/demo.{p_idx}.{e_idx}",
            })

            # 70% có ref tương ứng trong crawled references
            if e_idx <= int(n_entries * 0.7):
                ref_rows.append({
                    "arxiv_id": pid,
                    "ref_arxiv_id": f"ref_{p_idx}_{e_idx:03d}",
                    "ref_title": title,
                    "ref_authors": ["Nguyen, A.", "Tran, B."],
                    "ref_submission_date": f"{year}-05-01",
                    "ref_s2_id": f"s2_{p_idx}_{e_idx}",
                    "doi": f"10.1000/demo.{p_idx}.{e_idx}",
                })

        # Thêm 5 ref rác (không ai cite)
        for r_idx in range(1, 6):
            ref_rows.append({
                "arxiv_id": pid,
                "ref_arxiv_id": f"dummy_{p_idx}_{r_idx}",
                "ref_title": f"Unrelated Study {r_idx}",
                "ref_authors": ["Le, C."],
                "ref_submission_date": "2015-01-01",
                "ref_s2_id": f"dummy_s2_{p_idx}_{r_idx}",
            })

        # Tạo file nhãn manual cho các bài manual
        if is_manual:
            manual_labels = []
            for e_idx in range(1, n_entries + 1):
                ckey = f"cite_{p_idx}_{e_idx}"
                gt = f"ref_{p_idx}_{e_idx:03d}" if e_idx <= int(n_entries * 0.7) else None
                manual_labels.append({
                    "citation_key": ckey,
                    "groundtruth_arxiv_id": gt,
                    "label_status": "match" if gt else "no_match",
                    "review_status": "match" if gt else "no_match",
                    "source": "manual",
                })
            save_labels(pid, manual_labels, labels_dir)

    write_json(bib_file, bib_rows)
    write_json(ref_file, ref_rows)
    LOG.info("Đã tạo dữ liệu mẫu với %d bài báo, sẵn sàng chạy pipeline!", total_papers)


def _read_elements_from_zip(zip_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Đọc elements.jsonl trực tiếp trong ZIP M2 (không giải nén ra đĩa)."""
    if not zip_path.exists():
        return [], str(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if Path(n).name == "elements.jsonl"]
        if not members:
            return [], str(zip_path)
        raw = zf.read(members[0]).decode("utf-8-sig")
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return records, f"{zip_path}!{members[0]}"


def run_preparation_pipeline(
    tables_dir: Path,
    labels_dir: Path,
    k: int = 1,
    seed: int = 42,
    demo: bool = False,
    max_auto: int = 0,
    elements_path: Path | None = None,
    elements_zip: Path | None = None,
    prepared_dataset_dir: Path | None = None,
) -> dict[str, Any]:
    """Quy trình chuẩn bị dữ liệu đầy đủ."""
    if demo:
        create_demo_data_if_missing(tables_dir, labels_dir, k=k)

    bib_path = tables_dir / "bibtex.json"
    ref_path = tables_dir / "references.json"

    if not bib_path.exists() or not ref_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {bib_path} hoặc {ref_path}. "
            "Hãy chạy Milestone 1 và 2 trước, hoặc truyền cờ --demo để chạy thử nghiệm!"
        )

    all_bib = read_json(bib_path)
    all_refs = read_json(ref_path)
    from src.m3_matching.references_io import enrich_from_tables_dir

    all_refs = enrich_from_tables_dir(all_refs, tables_dir)

    LOG.info("Đã đọc %d dòng BibTeX và %d dòng References.", len(all_bib), len(all_refs))

    elements_label = ""
    if elements_zip is not None:
        element_records, elements_label = _read_elements_from_zip(elements_zip)
    else:
        elements_path = elements_path or (tables_dir / "elements.jsonl")
        elements_label = str(elements_path)
        element_records = read_jsonl(elements_path) if elements_path.exists() else []

    if element_records:
        LOG.info(
            "Đã đọc %d dòng elements từ %s: cite_count sẽ được đếm từ lệnh \\cite trong M2.",
            len(element_records),
            elements_label,
        )
    else:
        LOG.warning(
            "Không có elements.jsonl (%s): cite_count sẽ = 0 cho mọi cặp (sentinel). "
            "Truyền --elements-zip (ZIP M2) hoặc --elements-path nếu muốn dùng đặc trưng này.",
            elements_label,
        )

    # 1. Tập bài báo có đủ cả BibTeX (M2) lẫn references (M1)
    bibs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for b in all_bib:
        bibs_by_paper.setdefault(b["arxiv_id"], []).append(b)
    refs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for r in all_refs:
        refs_by_paper.setdefault(r["arxiv_id"], []).append(r)

    # Chỉ paper có ít nhất 1 reference mang arXiv ID mới có ứng viên để ghép.
    bib_papers = {pid for pid, rows in bibs_by_paper.items() if rows}
    ref_papers = {
        pid for pid, rows in refs_by_paper.items()
        if any(r.get("ref_arxiv_id") for r in rows)
    }
    available_papers = sorted(bib_papers & ref_papers)
    available_set = set(available_papers)

    def n_arxiv_refs(pid: str) -> int:
        return sum(1 for r in refs_by_paper.get(pid, []) if r.get("ref_arxiv_id"))

    # 2. Đọc nhãn đã có, bỏ các bài không đủ dữ liệu để ghép cặp
    labels = load_labels(labels_dir)
    orphan_labels = sorted(set(labels) - available_set)
    orphan_query_count = sum(len(labels[pid]) for pid in orphan_labels)
    if orphan_labels:
        LOG.warning(
            "Bỏ qua %d bài có nhãn nhưng thiếu BibTeX hoặc references arXiv: %s",
            len(orphan_labels),
            orphan_labels[:10],
        )
        labels = {pid: rows for pid, rows in labels.items() if pid in available_set}

    manual_papers = [
        pid for pid, entries in labels.items()
        if any(e.get("source") == "manual" for e in entries)
    ]
    LOG.info("Tìm thấy %d bài báo gán nhãn thủ công (Manual): %s", len(manual_papers), manual_papers)

    # 3. Tự động gán nhãn cho các bài chưa có nhãn (mọi entry của paper được chọn).
    #    Ưu tiên paper ít cặp (bib × ref arXiv) trước để chạy nhanh và tránh phình Parquet.
    auto_candidates = [
        pid for pid in available_papers
        if pid not in labels and bibs_by_paper.get(pid) and n_arxiv_refs(pid) > 0
    ]
    auto_candidates.sort(key=lambda pid: len(bibs_by_paper[pid]) * n_arxiv_refs(pid))

    existing_auto = sum(
        1 for entries in labels.values()
        if any(e.get("source") == "auto" for e in entries)
    )
    n_auto_added = 0
    for pid in auto_candidates:
        if max_auto and existing_auto + n_auto_added >= max_auto:
            break
        p_bibs = bibs_by_paper.get(pid, [])
        p_refs = refs_by_paper.get(pid, [])
        auto_rows = auto_label_publication(pid, p_bibs, p_refs)
        if auto_rows:
            # Lưu riêng từng publication để giữ provenance và hỗ trợ chạy tiếp.
            save_labels(pid, auto_rows, labels_dir)
            labels[pid] = auto_rows
            n_auto_added += 1
    if n_auto_added:
        LOG.info("Đã lưu %d auto label files riêng lẻ", n_auto_added)

    # 4. Kiểm tra quota
    bibtex_counts = {
        pid: len(bibs_by_paper[pid])
        for pid in available_papers
    }
    bibtex_keys = {
        pid: {str(row.get("citation_key") or "").strip() for row in bibs_by_paper[pid]}
        for pid in available_papers
    }
    validate_label_quota(
        labels,
        n_publications_total=len(available_papers),
        k=k,
        bibtex_counts=bibtex_counts,
        bibtex_keys=bibtex_keys,
    )
    LOG.info("Đã kiểm tra Hạn mức (Quota) của thầy: ĐẠT CHUẨN 100%%!")

    # 5. Phân chia tập dữ liệu train / valid / test
    partition_map = split_publications(labels, seed=seed, k=k)
    test_pids = [pid for pid, p in partition_map.items() if p == "test"]
    valid_pids = [pid for pid, p in partition_map.items() if p == "valid"]
    train_pids = [pid for pid, p in partition_map.items() if p == "train"]

    LOG.info("Phân chia tập (k=%d, seed=%d):", k, seed)
    LOG.info("  - Test set  (%d bài): %s", len(test_pids), test_pids)
    LOG.info("  - Valid set (%d bài): %s", len(valid_pids), valid_pids)
    LOG.info("  - Train set (%d bài): %s", len(train_pids), train_pids)

    # 6. Sinh tập dữ liệu cặp (Pairs Dataset) với 14 đặc trưng và nhãn 0/1
    LOG.info("Đang sinh tập dữ liệu cặp ứng viên và trích xuất 14 đặc trưng...")
    
    # Default to the legacy folder; review runs can select a new snapshot path.
    my_m3_dir = tables_dir.parent
    prepared_dataset_dir = Path(prepared_dataset_dir) if prepared_dataset_dir else my_m3_dir / "prepared_dataset"
    if prepared_dataset_dir.exists() and any(prepared_dataset_dir.iterdir()):
        raise FileExistsError(
            f"Prepared dataset output directory is not empty; refusing to overwrite: {prepared_dataset_dir}"
        )
    prepared_dataset_dir.mkdir(parents=True, exist_ok=True)
    
    datasets = generate_training_dataset(
        labels=labels,
        partition_map=partition_map,
        bibtex_records=all_bib,
        reference_records=all_refs,
        output_dir=prepared_dataset_dir,
        element_records=element_records,
    )

    # Auditable query and candidate-coverage counts for this snapshot.
    pair_query_keys = {
        (str(row["arxiv_id"]), str(row["citation_key"]))
        for split_rows in datasets.values()
        for row in split_rows
    }
    query_breakdown, gt_outside = build_query_stats(
        labels, partition_map, refs_by_paper, pair_query_keys
    )
    query_totals = _sum_query_buckets([
        counts
        for splits in query_breakdown.values()
        for counts in splits.values()
    ])
    query_stats_by_partition: dict[str, dict[str, int]] = {}
    for partition in ("train", "valid", "test", "unassigned"):
        buckets = [
            splits[partition]
            for splits in query_breakdown.values()
            if partition in splits
        ]
        if buckets:
            query_stats_by_partition[partition] = _sum_query_buckets(buckets)

    unresolved = query_totals["unknown"]
    confirmed_no_match = query_totals["no_match"]
    known_gt = query_totals["match"] + query_totals["gt_outside_candidate_pool"]
    inside_gt = query_totals["match"]
    labeled_queries = query_totals["total"] - unresolved
    automatic_stats = query_breakdown.get("automatic", {})
    automatic_queries_total = sum(bucket["total"] for bucket in automatic_stats.values())
    automatic_queries_unknown = sum(bucket["unknown"] for bucket in automatic_stats.values())
    evaluation_scope_by_partition = {
        partition: {
            **counts,
            "queries_labeled": counts["total"] - counts["unknown"],
            "mrr_at_5_evaluated_denominator": counts["match"],
            "mrr_at_5_strict_denominator": counts["total"] - counts["unknown"],
        }
        for partition, counts in query_stats_by_partition.items()
    }
    evaluation_scope = {
        "queries_total": query_totals["total"],
        "queries_labeled": labeled_queries,
        "queries_with_known_gt": known_gt,
        "queries_with_gt_inside_candidate_pool": inside_gt,
        "queries_with_gt_outside_candidate_pool": query_totals["gt_outside_candidate_pool"],
        "queries_unknown": unresolved,
        "queries_confirmed_no_match": confirmed_no_match,
        "queries_with_pairs": query_totals["queries_with_pairs"],
        "queries_without_pairs": query_totals["queries_without_pairs"],
        "candidate_coverage": (inside_gt / known_gt) if known_gt else None,
        "mrr_at_5_evaluated_denominator": inside_gt,
        "mrr_at_5_strict_denominator": labeled_queries,
        "by_partition": evaluation_scope_by_partition,
        "note": (
            "Evaluated MRR uses only confirmed GTs inside the candidate pool. Strict "
            "MRR uses every resolved labeled query on the evaluated partition; "
            "no_match and GT-outside queries contribute RR=0. Unknown queries are "
            "unresolved, excluded from both MRR denominators and training pairs, "
            "and are never relabeled as no_match."
        ),
    }

    report = {
        "publications_with_labels": len(labels),
        "queries_total": query_totals["total"],
        "queries_with_candidate_pairs": len(pair_query_keys),
        "gt_null_queries": unresolved + confirmed_no_match,
        "gt_null_unresolved_queries": unresolved,
        "confirmed_no_match_queries": confirmed_no_match,
        "automatic_queries_total": automatic_queries_total,
        "automatic_queries_unresolved": automatic_queries_unknown,
        "automatic_labeling_complete": automatic_queries_unknown == 0,
        "gt_outside_candidate_pool": gt_outside,
        "gt_outside_candidate_pool_count": len(gt_outside),
        "query_breakdown_by_source_and_split": query_breakdown,
        "query_stats_by_source_and_split": query_breakdown,
        "query_stats_by_partition": query_stats_by_partition,
        "query_totals": query_totals,
        "evaluation_scope": evaluation_scope,
        "pairs": {name: {"positive": sum(r["label"] == 1 for r in rows), "negative": sum(r["label"] == 0 for r in rows), "total": len(rows)} for name, rows in datasets.items()},
        "publications_missing_bibtex_or_arxiv_references": len(orphan_labels),
        "orphan_label_queries_excluded": orphan_query_count,
        "queries_omitted_from_pairs": query_totals["queries_without_pairs"] + orphan_query_count,
    }
    report_path = prepared_dataset_dir / "dataset_report.json"
    write_json(report_path, report)

    summary: dict[str, Any] = {
        "k_members": k,
        "n_manual_papers": len(manual_papers),
        "n_auto_papers_added_this_run": n_auto_added,
        "total_labeled_papers": len(labels),
        "splits": {
            "train": {
                "n_papers": len(train_pids),
                "n_pairs": len(datasets["train"]),
                "n_positives": sum(1 for r in datasets["train"] if r["label"] == 1),
                "n_negatives": sum(1 for r in datasets["train"] if r["label"] == 0),
            },
            "valid": {
                "n_papers": len(valid_pids),
                "n_pairs": len(datasets["valid"]),
                "n_positives": sum(1 for r in datasets["valid"] if r["label"] == 1),
                "n_negatives": sum(1 for r in datasets["valid"] if r["label"] == 0),
            },
            "test": {
                "n_papers": len(test_pids),
                "n_pairs": len(datasets["test"]),
                "n_positives": sum(1 for r in datasets["test"] if r["label"] == 1),
                "n_negatives": sum(1 for r in datasets["test"] if r["label"] == 0),
            },
        },
        "exported_files": [
            str(prepared_dataset_dir / "train_pairs.parquet"),
            str(prepared_dataset_dir / "valid_pairs.parquet"),
            str(prepared_dataset_dir / "test_pairs.parquet"),
            str(prepared_dataset_dir / "dataset_pairs.parquet"),
            str(report_path),
        ],
        "feature_names": feature_names(),
        "dataset_report": str(report_path),
        "audit": report,
    }

    return summary


def main() -> None:
    _configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Script chuẩn bị dữ liệu (Milestone 3)")
    parser.add_argument("--k", type=int, default=1, help="Số lượng thành viên nhóm (1 hoặc 2)")
    parser.add_argument("--seed", type=int, default=42, help="Seed ngẫu nhiên chia split (mặc định 42)")
    parser.add_argument("--tables-dir", type=Path, default=TABLES_DIR, help="Thư mục chứa tables (mặc định data/tables)")
    parser.add_argument("--labels-dir", type=Path, default=DATA_DIR / "labels", help="Thư mục chứa labels (mặc định data/labels)")
    parser.add_argument("--demo", action="store_true", help="Tạo dữ liệu mẫu và chạy thử nếu chưa có dữ liệu M1/M2")
    parser.add_argument("--max-auto", type=int, default=0, help="Tổng số bài auto tối đa (0 = gán tất cả)")
    parser.add_argument("--elements-path", type=Path, default=None, help="elements.jsonl (mặc định <tables-dir>/elements.jsonl)")
    parser.add_argument("--elements-zip", type=Path, default=None, help="ZIP M2 chứa elements.jsonl (đọc trực tiếp, không giải nén)")
    parser.add_argument(
        "--prepared-dataset-dir",
        type=Path,
        default=None,
        help="Thư mục output riêng cho snapshot dataset; phải rỗng hoặc chưa tồn tại",
    )
    args = parser.parse_args()

    print("=================================================================")
    print("      QUY TRÌNH CHUẨN BỊ DỮ LIỆU HUẤN LUYỆN (MILESTONE 3)       ")
    print("=================================================================")
    
    summary = run_preparation_pipeline(
        tables_dir=args.tables_dir,
        labels_dir=args.labels_dir,
        k=args.k,
        seed=args.seed,
        demo=args.demo,
        max_auto=args.max_auto,
        elements_path=args.elements_path,
        elements_zip=args.elements_zip,
        prepared_dataset_dir=args.prepared_dataset_dir,
    )

    print("\n>>> BÁO CÁO BÀN GIAO DỮ LIỆU:")
    print(f"- Số lượng đặc trưng: {len(summary['feature_names'])} features")
    print(f"  {summary['feature_names']}")
    print(f"- Tập Train: {summary['splits']['train']['n_pairs']} cặp ({summary['splits']['train']['n_positives']} positive, {summary['splits']['train']['n_negatives']} negative)")
    print(f"- Tập Valid: {summary['splits']['valid']['n_pairs']} cặp ({summary['splits']['valid']['n_positives']} positive, {summary['splits']['valid']['n_negatives']} negative)")
    print(f"- Tập Test : {summary['splits']['test']['n_pairs']} cặp ({summary['splits']['test']['n_positives']} positive, {summary['splits']['test']['n_negatives']} negative)")
    print("\n>>> CÁC FILE ĐÃ XUẤT ĐỂ ĐƯA VÀO HUẤN LUYỆN:")
    for f in summary["exported_files"]:
        print(f"  [x] {f}")
    print("=================================================================\n")


if __name__ == "__main__":
    main()
