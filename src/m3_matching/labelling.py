"""
Ground truth: pair BibTeX entry ↔ crawled reference CÙNG publication.

Ràng buộc đề:
- Manual: ≥ 5 publications, mỗi paper ≥ 20 labeled entries, tổng ≥ 100
- Auto (heuristic / string similarity): ≥ 10% publications NGOÀI manual pool,
  và auto label MỌI BibTeX entry của paper được chọn
- 1 entry tối đa 1 true reference; không khớp → groundtruth = None (all-negative row)

Format nội bộ:
data/labels/{manual,automatic}/{arxiv_id}.json
  {"citation_key": "...", "groundtruth_arxiv_id": "2310.12345"|null, "source": "manual"|"auto"}
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from src.common.config import (
    MIN_AUTO_LABEL_FRACTION,
    MIN_LABELED_ENTRIES_PER_MANUAL_PAPER,
    MIN_LABELED_ENTRIES_TOTAL,
    MIN_MANUAL_PUBLICATIONS,
    TABLES_DIR,
)
from src.common.io import read_json
from src.m3_matching.cleaning import (
    prepare_bibtex_record,
    prepare_reference_record,
)
from src.m3_matching.features import (
    author_overlap,
    title_similarity,
    year_distance,
)

LabelSource = Literal["manual", "auto"]


def _match_one_prepared(
    bib_clean: dict[str, Any],
    prepared_refs: list[dict[str, Any]],
) -> str | None:
    """Phần lõi của auto_match_one, nhận dữ liệu đã chuẩn hóa để tránh lặp lại."""
    if not prepared_refs:
        return None

    doi_bib = bib_clean.get("doi_norm")
    title_bib = bib_clean.get("title_norm") or ""

    candidates_with_scores: list[tuple[float, str]] = []

    for ref_clean in prepared_refs:
        ref_arxiv_id = ref_clean.get("ref_arxiv_id_norm") or ref_clean.get("ref_arxiv_id")
        if not ref_arxiv_id:
            continue

        # Quy tắc 1: Khớp DOI chính xác (sau chuẩn hóa)
        doi_ref = ref_clean.get("doi_norm")
        if doi_bib and doi_ref and doi_bib == doi_ref:
            return str(ref_arxiv_id)

        # Quy tắc 2: Khớp tiêu đề tuyệt đối
        title_ref = ref_clean.get("title_norm") or ""
        if len(title_bib) >= 8 and title_bib == title_ref:
            return str(ref_arxiv_id)

        # Tính độ tương đồng
        t_sim = title_similarity(bib_clean, ref_clean)
        a_sim = author_overlap(bib_clean, ref_clean)
        y_diff = year_distance(bib_clean, ref_clean)

        # Điều kiện gán tự động khắt khe (Precision cao):
        # - Title similarity cao (≥ 0.88)
        # - Có tác giả trùng (overlap > 0 hoặc title cực cao ≥ 0.95)
        # - Năm lệch không quá 1 (hoặc một bên không rõ năm)
        is_year_ok = (y_diff < 0) or (y_diff <= 1.0)
        is_author_ok = (a_sim > 0.0) or (t_sim >= 0.95)

        if t_sim >= 0.88 and is_author_ok and is_year_ok:
            composite_score = t_sim * 0.7 + a_sim * 0.2 + (0.1 if (0 <= y_diff <= 1) else 0.0)
            candidates_with_scores.append((composite_score, str(ref_arxiv_id)))

    if not candidates_with_scores:
        return None

    candidates_with_scores.sort(key=lambda x: x[0], reverse=True)
    best_score, best_ref_id = candidates_with_scores[0]

    # Nếu có candidate thứ 2 quá sát điểm (< 0.05) -> ambiguity -> không gán
    if len(candidates_with_scores) > 1:
        second_score = candidates_with_scores[1][0]
        if best_score - second_score < 0.05 and candidates_with_scores[1][1] != best_ref_id:
            return None

    return best_ref_id


def auto_match_one(
    bib_entry: dict[str, Any],
    references: list[dict[str, Any]],
) -> str | None:
    """
    Heuristic matcher (regex / string similarity / rules).
    Chỉ so với các crawled references CỦA CÙNG bài báo đang cite.

    Quy tắc đối sánh chính xác cao:
    1. Exact DOI trùng khớp
    2. Exact title trùng khớp (khi title đủ dài ≥ 8 ký tự)
    3. Fuzzy title (token_sort_ratio ≥ 88%) + Trùng ít nhất 1 tác giả + Chênh lệch năm ≤ 1
    Nếu không thỏa điều kiện hoặc có xung đột không rõ ràng -> trả về None.
    """
    if not references:
        return None
    bib_clean = prepare_bibtex_record(bib_entry)
    prepared_refs = [prepare_reference_record(ref) for ref in references]
    return _match_one_prepared(bib_clean, prepared_refs)


def auto_label_publication(
    arxiv_id: str,
    bib_entries: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Gán nhãn tự động cho MỌI BibTeX entry của 1 paper (bắt buộc theo quy định M3).
    Nếu bib_entries / references là None, tự động đọc từ data/tables/bibtex.json và references.json (hoặc .jsonl).

    References được chuẩn hóa MỘT LẦN cho cả paper để tránh O(bib × ref) lặp lại.
    """
    if bib_entries is None:
        all_bib = read_json(TABLES_DIR / "bibtex.json")
        bib_entries = [b for b in all_bib if b.get("arxiv_id") == arxiv_id]

    if references is None:
        all_refs = read_json(TABLES_DIR / "references.json")
        references = [r for r in all_refs if r.get("arxiv_id") == arxiv_id]

    prepared_refs = [prepare_reference_record(ref) for ref in references]

    labeled_rows: list[dict[str, Any]] = []
    for bib in bib_entries:
        citation_key = bib.get("citation_key")
        if not citation_key:
            continue
        gt_id = _match_one_prepared(prepare_bibtex_record(bib), prepared_refs)
        labeled_rows.append({
            "citation_key": citation_key,
            "groundtruth_arxiv_id": gt_id,
            "source": "auto",
        })

    return labeled_rows


def load_labels(labels_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """
    Đọc tất cả file nhãn từ:
    - labels/manual/{arxiv_id}.json
    - labels/automatic/{arxiv_id}.json
    -> {arxiv_id: [label_dict, ...]}
    """
    import json
    
    labels_dir = Path(labels_dir)
    result: dict[str, list[dict[str, Any]]] = {}
    if not labels_dir.exists():
        return result

    # Đọc từ manual/ folder
    manual_dir = labels_dir / "manual"
    if manual_dir.exists():
        for json_file in sorted(manual_dir.glob("*.json")):
            arxiv_id = json_file.stem
            with open(json_file, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if rows:
                result[arxiv_id] = rows

    # Đọc từ automatic/ folder
    auto_dir = labels_dir / "automatic"
    if auto_dir.exists():
        for json_file in sorted(auto_dir.glob("*.json")):
            arxiv_id = json_file.stem
            with open(json_file, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if rows:
                # Merge với existing nếu có (combine manual + auto)
                if arxiv_id in result:
                    result[arxiv_id].extend(rows)
                else:
                    result[arxiv_id] = rows

    return result


def save_labels(arxiv_id: str, rows: list[dict[str, Any]], labels_dir: Path) -> Path:
    """
    Ghi danh sách nhãn của 1 publication vào:
    - labels/manual/{arxiv_id}.json (nếu source="manual")
    - labels/automatic/{arxiv_id}.json (nếu source="auto")
    """
    import json
    
    labels_dir = Path(labels_dir)
    
    # Determine source từ rows
    source = rows[0].get("source", "auto") if rows else "auto"
    
    # Create subfolder dựa trên source
    if source == "manual":
        subfolder = labels_dir / "manual"
    else:
        subfolder = labels_dir / "automatic"
    
    subfolder.mkdir(parents=True, exist_ok=True)
    out_path = subfolder / f"{arxiv_id}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    
    return out_path


def validate_label_quota(
    labels: dict[str, list[dict[str, Any]]],
    n_publications_total: int,
    k: int = 1,
) -> None:
    """
    Kiểm tra toàn bộ hạn mức (quota) gán nhãn theo đúng quy định của thầy:
    - Nhóm k thành viên (mặc định k=1, nhóm 2 người k=2):
      1. Số bài manual ≥ 5 * k (tối thiểu 5 bài cho 1 người, 10 bài cho 2 người)
      2. Mỗi bài manual ≥ MIN_LABELED_ENTRIES_PER_MANUAL_PAPER (20 entries)
      3. Tổng số entry manual ≥ 100 * k
      4. Số bài auto ≥ max(ceil(10% số bài ngoài manual), 2 * k)
    """
    if not labels:
        raise ValueError("Chưa có dữ liệu gán nhãn nào trong thư mục labels!")

    manual_papers: dict[str, int] = {}
    auto_papers: set[str] = set()

    for arxiv_id, entries in labels.items():
        manual_count = sum(1 for e in entries if e.get("source") == "manual")
        auto_count = sum(1 for e in entries if e.get("source") == "auto")
        
        if manual_count > 0:
            manual_papers[arxiv_id] = manual_count
        elif auto_count > 0:
            auto_papers.add(arxiv_id)

    # 1. Kiểm tra số bài manual
    n_manual = len(manual_papers)
    min_manual_req = MIN_MANUAL_PUBLICATIONS * k
    if n_manual < min_manual_req:
        raise ValueError(
            f"Thiếu số lượng bài gán nhãn thủ công: {n_manual} < {min_manual_req} bài (k={k})."
        )

    # 2. Kiểm tra mỗi bài manual ≥ 20 entries
    for paper_id, count in manual_papers.items():
        if count < MIN_LABELED_ENTRIES_PER_MANUAL_PAPER:
            raise ValueError(
                f"Bài manual {paper_id} chỉ có {count} entries < {MIN_LABELED_ENTRIES_PER_MANUAL_PAPER} entries."
            )

    # 3. Kiểm tra tổng số entries manual ≥ 100 * k
    total_manual_entries = sum(manual_papers.values())
    min_total_req = MIN_LABELED_ENTRIES_TOTAL * k
    if total_manual_entries < min_total_req:
        raise ValueError(
            f"Tổng số entry manual là {total_manual_entries} < {min_total_req} entries (k={k})."
        )

    # 4. Kiểm tra số lượng bài auto ≥ 10% số bài ngoài nhóm manual và ≥ 2*k
    remaining_pool = max(0, n_publications_total - n_manual)
    required_auto = max(math.ceil(MIN_AUTO_LABEL_FRACTION * remaining_pool), 2 * k)
    n_auto = len(auto_papers)
    if n_auto < required_auto:
        raise ValueError(
            f"Số bài gán nhãn tự động chưa đủ: {n_auto} < {required_auto} bài "
            f"(yêu cầu ≥ {MIN_AUTO_LABEL_FRACTION*100:.0f}% của {remaining_pool} bài còn lại và ≥ {2*k})."
        )
