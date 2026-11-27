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

import re
from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR, TABLES_DIR
from src.common.ids import normalize_arxiv_id
from src.common.io import read_json, read_jsonl, write_parquet_shard
from src.m3_matching.cleaning import (
    prepare_bibtex_record,
    prepare_reference_record,
)
from src.m3_matching.features import feature_names, pair_feature_vector
from src.m3_matching.split import Partition, split_publications

# Bắt các lệnh cite của LaTeX: \cite{a,b}, \citep[trang]{c}, \citet*{d}, ...
_CITE_RE = re.compile(r"\\([a-zA-Z]*cite[a-zA-Z]*\*?)\s*(?:\[[^\]]*\])*\s*\{([^{}]+)\}", re.I)

# Chỉ các trạng thái này mới chứng minh query không có candidate đúng.
_NO_MATCH_STATUSES = {"no_match", "confirmed_no_match", "negative"}


def build_citation_context_map(
    element_records: list[dict[str, Any]] | None,
) -> dict[str, dict[str, dict[str, float]]]:
    """
    Đếm số lần mỗi citation_key được cite trong toàn văn của từng paper (M2 elements).

    Trả về: {arxiv_id: {citation_key: {"cite_count": n, "is_cited_in_text": 1.0}}}
    Nếu không có elements (M2 hierarchy) thì trả về dict rỗng; ``cite_count`` sẽ = 0.
    """
    contexts: dict[str, dict[str, dict[str, float]]] = {}
    for element in element_records or []:
        arxiv_id = element.get("arxiv_id")
        content = element.get("content") or ""
        if not arxiv_id or not content:
            continue

        paper_ctx = contexts.setdefault(arxiv_id, {})
        for match in _CITE_RE.finditer(str(content)):
            for raw_key in match.group(2).split(","):
                citation_key = raw_key.strip()
                if not citation_key:
                    continue
                entry = paper_ctx.setdefault(
                    citation_key,
                    {"cite_count": 0.0, "is_cited_in_text": 1.0},
                )
                entry["cite_count"] += 1.0

    return contexts


def _normalize_gt_id(gt_id: str | None) -> str | None:
    """Chuẩn hóa groundtruth_arxiv_id (bỏ prefix arXiv: / version vN) để khớp với ref_arxiv_id_norm."""
    if gt_id is None:
        return None
    text = str(gt_id).strip()
    if not text:
        return None
    try:
        return normalize_arxiv_id(text)
    except ValueError:
        return text


def build_paper_pairs(
    arxiv_id: str,
    bib_entries: list[dict[str, Any]],
    references: list[dict[str, Any]],
    labels_for_paper: list[dict[str, Any]],
    partition: Partition,
    citation_context: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    Tạo tất cả các cặp (bibtex_entry, reference_candidate) trong cùng một bài báo.
    - Chỉ tạo cặp cho các BibTeX entries đã được gán nhãn (manual hoặc auto).
    - Mỗi ``ref_arxiv_id`` chỉ xuất hiện một lần (dedup reference trùng trong M1).
    - Cặp đúng (positive): ref_arxiv_id == groundtruth_arxiv_id -> label = 1
    - Cặp sai (negative): ref_arxiv_id != groundtruth_arxiv_id -> label = 0
    - GT-null ``no_match`` (reviewer xác nhận không có candidate đúng) sinh hàng toàn 0.
    - GT-null ``unknown`` (chưa xác định được GT) không sinh pairs.
    - GT ngoài candidate pool sinh hàng toàn 0 và giữ nguyên GT để theo dõi coverage.
    - ``citation_context`` (tùy chọn) cung cấp ``cite_count`` cho từng citation_key.
    """
    label_map: dict[str, str | None] = {}
    status_map: dict[str, str] = {}
    for row in labels_for_paper:
        key = row.get("citation_key")
        if key is None or not str(key).strip():
            raise ValueError(
                f"Label thiếu citation_key trong publication {arxiv_id}."
            )
        key = str(key).strip()
        if key in label_map:
            raise ValueError(
                f"citation_key bị gán nhãn trùng trong publication "
                f"{arxiv_id}: {key}."
            )
        label_map[key] = row.get("groundtruth_arxiv_id")
        status_map[key] = str(
            row.get("label_status") or row.get("review_status") or ""
        ).strip().lower()

    # Accept only confirmed matches or confirmed no-match outcomes. Legacy
    # records without an explicit status infer match from a GT, otherwise unknown.
    labeled_bibs = []
    for bib in bib_entries:
        key = str(bib.get("citation_key") or "").strip()
        if key not in label_map:
            continue
        gt_id = _normalize_gt_id(label_map[key])
        status = status_map.get(key, "")
        if not status:
            status = "match" if gt_id is not None else "unknown"

        if status == "unknown":
            if gt_id is not None:
                raise ValueError(
                    f"Label unknown nhưng có groundtruth_arxiv_id: {arxiv_id}/{key}."
                )
            continue
        if status in {"match", "confirmed_match"}:
            if gt_id is None:
                raise ValueError(
                    f"Label match nhưng thiếu groundtruth_arxiv_id: {arxiv_id}/{key}."
                )
            labeled_bibs.append(bib)
            continue
        if status in _NO_MATCH_STATUSES:
            labeled_bibs.append(bib)
            continue
        raise ValueError(
            f"label_status không hợp lệ: {status!r}, publication={arxiv_id}, citation_key={key}."
        )
    if not labeled_bibs or not references:
        return []

    bib_keys = [str(b["citation_key"]).strip() for b in labeled_bibs]
    if len(bib_keys) != len(set(bib_keys)):
        raise ValueError(
            f"BibTeX có citation_key trùng trong publication {arxiv_id}."
        )

    # Chuẩn hóa + dedup reference theo ref_arxiv_id trong cùng paper
    clean_bibs = [prepare_bibtex_record(b) for b in labeled_bibs]
    clean_refs: list[dict[str, Any]] = []
    seen_ref_ids: set[str] = set()
    for reference in references:
        if not reference.get("ref_arxiv_id"):
            continue
        clean_ref = prepare_reference_record(reference)
        ref_id = clean_ref.get("ref_arxiv_id_norm") or clean_ref.get("ref_arxiv_id")
        if not ref_id or ref_id in seen_ref_ids:
            continue
        seen_ref_ids.add(ref_id)
        clean_refs.append(clean_ref)

    feat_names = feature_names()
    pairs: list[dict[str, Any]] = []

    for bib in clean_bibs:
        key = str(bib["citation_key"]).strip()
        gt_id = _normalize_gt_id(label_map.get(key))
        confirmed_no_match = status_map.get(key, "") in _NO_MATCH_STATUSES
        if confirmed_no_match and gt_id is not None and gt_id in seen_ref_ids:
            raise ValueError(
                f"Citation {key} trong publication {arxiv_id} được gán no_match "
                f"nhưng GT {gt_id} lại có trong candidate pool."
            )
        extra = citation_context.get(key) if citation_context else None

        for ref in clean_refs:
            ref_id = ref.get("ref_arxiv_id_norm") or ref.get("ref_arxiv_id")
            if not ref_id:
                continue

            # Nhãn nhị phân: 1 nếu trùng khớp ground truth, ngược lại 0.
            # GT ngoài pool hoặc no_match cũng đi qua đây -> hàng toàn 0.
            is_match = 1 if (not confirmed_no_match and gt_id is not None and ref_id == gt_id) else 0

            # Tính vector đặc trưng (truyền extra để cite_count không bị 0 vô ích)
            feats = pair_feature_vector(bib, ref, extra=extra)
            if len(feats) != len(feat_names):
                raise ValueError(
                    f"Feature dimension mismatch: {len(feats)} values but "
                    f"{len(feat_names)} names for {arxiv_id}/{key}/{ref_id}."
                )
            row_dict: dict[str, Any] = {
                "arxiv_id": arxiv_id,
                "partition": partition,
                "citation_key": key,
                "ref_arxiv_id": ref_id,
                "groundtruth_arxiv_id": gt_id,
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
    element_records: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Sinh toàn bộ tập dữ liệu cặp (pairs dataset) cho tất cả các bài báo trong partition_map.
    Lưu thành:
    - data/tables/dataset_pairs.parquet (toàn bộ)
    - data/tables/train_pairs.parquet
    - data/tables/valid_pairs.parquet
    - data/tables/test_pairs.parquet

    ``element_records`` (M2 elements) là tùy chọn: nếu có, ``cite_count`` được đếm
    từ các lệnh ``\\cite{...}`` trong toàn văn. Nếu không truyền, hàm tự đọc
    ``elements.jsonl`` trong ``output_dir`` khi file tồn tại.

    Trả về: {"train": [rows], "valid": [rows], "test": [rows]}
    """
    output_dir = output_dir or TABLES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if bibtex_records is None:
        bibtex_records = read_json(output_dir / "bibtex.json")
    if reference_records is None:
        from src.m3_matching.references_io import enrich_from_tables_dir

        reference_records = enrich_from_tables_dir(
            read_json(output_dir / "references.json"), output_dir)
    if element_records is None:
        elements_jsonl = output_dir / "elements.jsonl"
        if elements_jsonl.exists():
            element_records = read_jsonl(elements_jsonl)
        else:
            element_records = []

    citation_contexts = build_citation_context_map(element_records)

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
            citation_context=citation_contexts.get(arxiv_id),
        )

        dataset_by_split[partition].extend(pairs)
        all_pairs.extend(pairs)

    # Ghi ra các file Parquet để Người 2 sử dụng trực tiếp
    # Always write all four shards, including valid empty partitions.
    write_parquet_shard(output_dir / "dataset_pairs.parquet", all_pairs)
    for part_name, part_rows in dataset_by_split.items():
        write_parquet_shard(output_dir / f"{part_name}_pairs.parquet", part_rows)

    return dataset_by_split
