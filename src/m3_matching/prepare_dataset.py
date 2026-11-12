"""
Script thực thi trọn gói: Chuẩn bị dữ liệu cho Milestone 3.

Thực hiện toàn bộ 6 bước:
1. Đọc và chuẩn hóa dữ liệu từ bibtex.jsonl và references.jsonl.
2. Kiểm tra các nhãn thủ công (data/labels/*.jsonl) của nhóm.
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
import logging
import sys
from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR, TABLES_DIR
from src.common.io import read_jsonl, write_jsonl
from src.m3_matching.dataset import generate_training_dataset
from src.m3_matching.features import feature_names
from src.m3_matching.labelling import (
    auto_label_publication,
    load_labels,
    save_labels,
    validate_label_quota,
)
from src.m3_matching.split import split_publications

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger(__name__)


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

    bib_file = tables_dir / "bibtex.jsonl"
    ref_file = tables_dir / "references.jsonl"

    if bib_file.exists() and ref_file.exists():
        return

    LOG.info("Chưa có data/tables/bibtex.jsonl. Đang khởi tạo dữ liệu mẫu (demo) để kiểm thử...")

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
                    "source": "manual",
                })
            save_labels(pid, manual_labels, labels_dir)

    write_jsonl(bib_file, bib_rows)
    write_jsonl(ref_file, ref_rows)
    LOG.info("Đã tạo dữ liệu mẫu với %d bài báo, sẵn sàng chạy pipeline!", total_papers)


def run_preparation_pipeline(
    tables_dir: Path,
    labels_dir: Path,
    k: int = 1,
    seed: int = 42,
    demo: bool = False,
) -> dict[str, Any]:
    """Quy trình chuẩn bị dữ liệu đầy đủ."""
    if demo:
        create_demo_data_if_missing(tables_dir, labels_dir, k=k)

    bib_path = tables_dir / "bibtex.jsonl"
    ref_path = tables_dir / "references.jsonl"

    if not bib_path.exists() or not ref_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {bib_path} hoặc {ref_path}. "
            "Hãy chạy Milestone 1 và 2 trước, hoặc truyền cờ --demo để chạy thử nghiệm!"
        )

    all_bib = read_jsonl(bib_path)
    all_refs = read_jsonl(ref_path)

    LOG.info("Đã đọc %d dòng BibTeX và %d dòng References.", len(all_bib), len(all_refs))

    # 1. Tập bài báo có đủ cả BibTeX (M2) lẫn references (M1)
    bib_papers = {b["arxiv_id"] for b in all_bib if b.get("arxiv_id")}
    ref_papers = {r["arxiv_id"] for r in all_refs if r.get("arxiv_id")}
    available_papers = sorted(bib_papers & ref_papers)
    available_set = set(available_papers)

    bibs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for b in all_bib:
        bibs_by_paper.setdefault(b["arxiv_id"], []).append(b)
    refs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for r in all_refs:
        refs_by_paper.setdefault(r["arxiv_id"], []).append(r)

    # 2. Đọc nhãn đã có, bỏ các bài không đủ dữ liệu để ghép cặp
    labels = load_labels(labels_dir)
    orphan_labels = sorted(set(labels) - available_set)
    if orphan_labels:
        LOG.warning(
            "Bỏ qua %d bài có nhãn nhưng thiếu BibTeX hoặc references: %s",
            len(orphan_labels),
            orphan_labels[:10],
        )
        labels = {pid: rows for pid, rows in labels.items() if pid in available_set}

    manual_papers = [
        pid for pid, entries in labels.items()
        if any(e.get("source") == "manual" for e in entries)
    ]
    LOG.info("Tìm thấy %d bài báo gán nhãn thủ công (Manual): %s", len(manual_papers), manual_papers)

    # 3. Tự động gán nhãn cho các bài chưa có nhãn (mọi entry của paper được chọn)
    for pid in available_papers:
        if pid in labels:
            continue
        p_bibs = bibs_by_paper.get(pid, [])
        p_refs = refs_by_paper.get(pid, [])
        if not p_bibs or not p_refs:
            continue
        auto_rows = auto_label_publication(pid, p_bibs, p_refs)
        if auto_rows:
            save_labels(pid, auto_rows, labels_dir)
            labels[pid] = auto_rows

    # 4. Kiểm tra quota
    validate_label_quota(labels, n_publications_total=len(available_papers), k=k)
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
    datasets = generate_training_dataset(
        labels=labels,
        partition_map=partition_map,
        bibtex_records=all_bib,
        reference_records=all_refs,
        output_dir=tables_dir,
    )

    summary: dict[str, Any] = {
        "k_members": k,
        "n_manual_papers": len(manual_papers),
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
            str(tables_dir / "train_pairs.parquet"),
            str(tables_dir / "valid_pairs.parquet"),
            str(tables_dir / "test_pairs.parquet"),
            str(tables_dir / "dataset_pairs.parquet"),
        ],
        "feature_names": feature_names(),
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
