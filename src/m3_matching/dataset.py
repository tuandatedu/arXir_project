"""
Tạo bảng dữ liệu huấn luyện từ các cặp tài liệu cần so sánh (Task 5 & Task 6).

Kết quả bàn giao cho Người 2:
- Bảng dữ liệu cặp (bibtex_entry, crawled_reference) với:
  + Cột định danh: arxiv_id, citation_key, ref_arxiv_id, partition ('train' | 'valid' | 'test')
  + Cột nhãn: label (1 nếu là cặp đúng, 0 nếu không phải)
  + Các cột đặc trưng (features) trích xuất từ pair_feature_vector.
- Người 2 chỉ việc đọc bảng này để đưa vào scikit-learn / LightGBM / XGBoost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR, TABLES_DIR
from src.common.io import read_jsonl, write_parquet_shard
from src.m3_matching.cleaning import (
    prepare_bibtex_record,
    prepare_reference_record,
)
from src.m3_matching.features import feature_names, pair_feature_vector
from src.m3_matching.split import Partition, split_publications


def build_paper_pairs(
    arxiv_id: str,
    bib_entries: list[dict[str, Any]],
    references: list[dict[str, Any]],
    labels_for_paper: list[dict[str, Any]],
    partition: Partition,
) -> list[dict[str, Any]]:
    """
    Tạo tất cả các cặp (bibtex_entry, reference_candidate) trong cùng một bài báo.
    - Chỉ tạo cặp cho các BibTeX entries đã được gán nhãn (manual hoặc auto).
    - Cặp đúng (positive): ref_arxiv_id == groundtruth_arxiv_id -> label = 1
    - Cặp sai (negative): ref_arxiv_id != groundtruth_arxiv_id -> label = 0
    - Nếu groundtruth_arxiv_id is None -> toàn bộ các cặp của entry đó đều có label = 0.
    """
    label_map: dict[str, str | None] = {
        row["citation_key"]: row.get("groundtruth_arxiv_id")
        for row in labels_for_paper
        if "citation_key" in row
    }

    # Lọc bib entries đã có nhãn
    labeled_bibs = [b for b in bib_entries if b.get("citation_key") in label_map]
    if not labeled_bibs or not references:
        return []

    # Chuẩn hóa
    clean_bibs = [prepare_bibtex_record(b) for b in labeled_bibs]
    clean_refs = [prepare_reference_record(r) for r in references if r.get("ref_arxiv_id")]

    feat_names = feature_names()
    pairs: list[dict[str, Any]] = []

    for bib in clean_bibs:
        key = bib["citation_key"]
        gt_id = label_map.get(key)

        for ref in clean_refs:
            ref_id = ref.get("ref_arxiv_id_norm") or ref.get("ref_arxiv_id")
            if not ref_id:
                continue

            # Nhãn nhị phân: 1 nếu trùng khớp ground truth, ngược lại 0
            is_match = 1 if (gt_id is not None and ref_id == gt_id) else 0

            # Tính vector đặc trưng
            feats = pair_feature_vector(bib, ref)
            row_dict: dict[str, Any] = {
                "arxiv_id": arxiv_id,
                "partition": partition,
                "citation_key": key,
                "ref_arxiv_id": ref_id,
                "label": is_match,
            }
            # Gán từng đặc trưng theo tên cột
            for name, val in zip(feat_names, feats):
                row_dict[name] = val

            pairs.append(row_dict)

    return pairs


def generate_training_dataset(
    labels: dict[str, list[dict[str, Any]]],
    partition_map: dict[str, Partition],
    bibtex_records: list[dict[str, Any]] | None = None,
    reference_records: list[dict[str, Any]] | None = None,
    output_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Sinh toàn bộ tập dữ liệu cặp (pairs dataset) cho tất cả các bài báo trong partition_map.
    Lưu thành:
    - data/tables/dataset_pairs.parquet (toàn bộ)
    - data/tables/train_pairs.parquet
    - data/tables/valid_pairs.parquet
    - data/tables/test_pairs.parquet

    Trả về: {"train": [rows], "valid": [rows], "test": [rows]}
    """
    output_dir = output_dir or TABLES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if bibtex_records is None:
        bibtex_records = read_jsonl(TABLES_DIR / "bibtex.jsonl")
    if reference_records is None:
        reference_records = read_jsonl(TABLES_DIR / "references.jsonl")

    # Gom nhóm theo arxiv_id
    bibs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for b in bibtex_records:
        pid = b.get("arxiv_id")
        if pid:
            bibs_by_paper.setdefault(pid, []).append(b)

    refs_by_paper: dict[str, list[dict[str, Any]]] = {}
    for r in reference_records:
        pid = r.get("arxiv_id")
        if pid:
            refs_by_paper.setdefault(pid, []).append(r)

    dataset_by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "valid": [],
        "test": [],
    }

    all_pairs: list[dict[str, Any]] = []

    for arxiv_id, partition in partition_map.items():
        paper_labels = labels.get(arxiv_id, [])
        paper_bibs = bibs_by_paper.get(arxiv_id, [])
        paper_refs = refs_by_paper.get(arxiv_id, [])

        pairs = build_paper_pairs(
            arxiv_id=arxiv_id,
            bib_entries=paper_bibs,
            references=paper_refs,
            labels_for_paper=paper_labels,
            partition=partition,
        )

        dataset_by_split[partition].extend(pairs)
        all_pairs.extend(pairs)

    # Ghi ra các file Parquet để Người 2 sử dụng trực tiếp
    if all_pairs:
        write_parquet_shard(output_dir / "dataset_pairs.parquet", all_pairs)
    for part_name, part_rows in dataset_by_split.items():
        if part_rows:
            write_parquet_shard(output_dir / f"{part_name}_pairs.parquet", part_rows)

    return dataset_by_split
