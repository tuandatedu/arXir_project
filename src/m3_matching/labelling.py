
from __future__ import annotations

import json
import math
import zipfile

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


# ============================================================
# 1. MATCHING
# ============================================================

def _get_ref_id(ref_clean: dict[str, Any]) -> str | None:
    """Lấy arXiv ID đã chuẩn hóa của một reference."""

    ref_id = (
        ref_clean.get("ref_arxiv_id_norm")
        or ref_clean.get("ref_arxiv_id")
    )

    if ref_id is None:
        return None

    ref_id = str(ref_id).strip()

    return ref_id or None


def _get_year_difference(
    bib_clean: dict[str, Any],
    ref_clean: dict[str, Any],
) -> float:
    """
    Tính độ lệch năm.

    Giá trị âm được hiểu là không đủ dữ liệu năm,
    tương thích với cách sử dụng year_distance hiện tại.
    """

    try:
        difference = year_distance(bib_clean, ref_clean)

        if difference is None:
            return -1.0

        return float(difference)

    except (TypeError, ValueError):
        return -1.0


def _unique_match(matches: list[str]) -> str | None:
    """
    Chỉ chấp nhận kết quả nếu có đúng một reference ID duy nhất.
    Nhiều dòng trùng cùng một ID vẫn được xem là một candidate.
    """

    unique_ids = set(matches)

    if len(unique_ids) == 1:
        return next(iter(unique_ids))

    return None


def _match_one_prepared(
    bib_clean: dict[str, Any],
    prepared_refs: list[dict[str, Any]],
) -> str | None:
    """
    Matching một BibTeX entry với references của cùng publication.

    Thứ tự ưu tiên:
    1. Exact DOI.
    2. Exact title.
    3. Fuzzy title + author + year.

    Nếu có nhiều candidate không phân biệt được:
    trả về None để tránh gán nhãn sai.
    """

    if not prepared_refs:
        return None

    doi_bib = bib_clean.get("doi_norm")
    title_bib = bib_clean.get("title_norm") or ""

    # --------------------------------------------------------
    # Rule 1: Exact DOI
    # --------------------------------------------------------

    doi_matches = []

    if doi_bib:
        for ref_clean in prepared_refs:
            ref_id = _get_ref_id(ref_clean)

            if not ref_id:
                continue

            doi_ref = ref_clean.get("doi_norm")

            if doi_ref and doi_bib == doi_ref:
                doi_matches.append(ref_id)

    if doi_matches:
        return _unique_match(doi_matches)

    # --------------------------------------------------------
    # Rule 2: Exact title
    # --------------------------------------------------------

    title_matches = []

    if len(title_bib) >= 8:
        for ref_clean in prepared_refs:
            ref_id = _get_ref_id(ref_clean)

            if not ref_id:
                continue

            title_ref = ref_clean.get("title_norm") or ""

            if title_bib == title_ref:
                title_matches.append(ref_id)

    if title_matches:
        return _unique_match(title_matches)

    # --------------------------------------------------------
    # Rule 3: Fuzzy matching
    # --------------------------------------------------------

    # Mỗi reference ID chỉ giữ một điểm số tốt nhất.
    scores_by_ref: dict[str, float] = {}

    for ref_clean in prepared_refs:
        ref_id = _get_ref_id(ref_clean)

        if not ref_id:
            continue

        try:
            t_sim = float(title_similarity(bib_clean, ref_clean))
            a_sim = float(author_overlap(bib_clean, ref_clean))
        except (TypeError, ValueError):
            continue

        y_diff = _get_year_difference(bib_clean, ref_clean)

        # Điều kiện năm:
        # - y_diff < 0: thiếu dữ liệu năm.
        # - y_diff <= 1: chênh lệch không quá một năm.
        is_year_ok = y_diff < 0 or y_diff <= 1.0

        # Phải có tác giả trùng hoặc title cực kỳ giống.
        is_author_ok = a_sim > 0.0 or t_sim >= 0.95

        if (
            t_sim >= 0.88
            and is_author_ok
            and is_year_ok
        ):
            year_score = (
                0.1 if 0 <= y_diff <= 1.0 else 0.0
            )

            composite_score = (
                t_sim * 0.7
                + a_sim * 0.2
                + year_score
            )

            scores_by_ref[ref_id] = max(
                scores_by_ref.get(ref_id, float("-inf")),
                composite_score,
            )

    if not scores_by_ref:
        return None

    ranked = sorted(
        scores_by_ref.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    best_ref_id, best_score = ranked[0]

    # Nếu candidate thứ hai quá sát candidate tốt nhất,
    # không tự động chọn để tránh false positive.
    if len(ranked) > 1:
        second_ref_id, second_score = ranked[1]

        if (
            best_ref_id != second_ref_id
            and best_score - second_score < 0.05
        ):
            return None

    return best_ref_id


def auto_match_one(
    bib_entry: dict[str, Any],
    references: list[dict[str, Any]],
) -> str | None:
    """
    Tự động tìm ground truth cho một BibTeX entry.

    Chỉ so sánh với crawled references thuộc cùng publication.
    """

    if not references:
        return None

    bib_clean = prepare_bibtex_record(bib_entry)

    prepared_refs = [
        prepare_reference_record(ref)
        for ref in references
    ]

    return _match_one_prepared(
        bib_clean,
        prepared_refs,
    )


def _auto_null_reason(bib_clean: dict[str, Any], refs: list[dict[str, Any]]) -> str:
    """Audit category for a null heuristic result; does not affect matching."""
    candidates = [r for r in refs if _get_ref_id(r)]
    if not candidates:
        return "no_candidate_with_arxiv_id"
    title = str(bib_clean.get("title_norm") or "").strip()
    doi = str(bib_clean.get("doi_norm") or "").strip()
    authors = bib_clean.get("authors_norm") or []
    if not title and not doi and not authors:
        return "insufficient_bibtex_metadata"
    doi_hits = [r for r in candidates if doi and r.get("doi_norm") == doi]
    if len({_get_ref_id(r) for r in doi_hits}) > 1:
        return "ambiguous_doi_candidates"
    title_hits = [r for r in candidates if len(title) >= 8 and title == (r.get("title_norm") or "")]
    if len({_get_ref_id(r) for r in title_hits}) > 1:
        return "ambiguous_exact_title_candidates"
    # Conservative audit classification: possible near matches need review.
    scored = []
    for r in candidates:
        try:
            sim = float(title_similarity(bib_clean, r))
            author = float(author_overlap(bib_clean, r))
            year = _get_year_difference(bib_clean, r)
            if sim >= .80 and (author > 0 or sim >= .95) and (year < 0 or year <= 1):
                scored.append((_get_ref_id(r), sim))
        except (TypeError, ValueError):
            continue
    if len({item[0] for item in scored}) > 1:
        return "ambiguous_candidates"
    if not title and not doi:
        return "insufficient_title_or_doi_metadata"
    return "no_match_meets_heuristic_threshold"


# ============================================================
# 2. AUTOMATIC LABELING
# ============================================================

def auto_label_publication(
    arxiv_id: str,
    bib_entries: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Gán nhãn tự động cho TOÀN BỘ BibTeX entries của một publication.

    Nếu không truyền bib_entries hoặc references,
    hàm tự đọc từ TABLES_DIR.

    Mỗi BibTeX entry hợp lệ tạo đúng một label:
    {
        "citation_key": "...",
        "groundtruth_arxiv_id": "2310.12345" | None,
        "source": "auto"
    }
    """

    # --------------------------------------------------------
    # Load BibTeX
    # --------------------------------------------------------

    if bib_entries is None:
        all_bib = read_json(TABLES_DIR / "bibtex.json")

        bib_entries = [
            bib
            for bib in all_bib
            if str(bib.get("arxiv_id", "")).strip() == arxiv_id
        ]

    if not bib_entries:
        raise ValueError(
            f"Không tìm thấy BibTeX entries cho publication {arxiv_id}."
        )

    # --------------------------------------------------------
    # Load references
    # --------------------------------------------------------

    if references is None:
        from src.m3_matching.references_io import enrich_from_tables_dir

        all_refs = enrich_from_tables_dir(
            read_json(TABLES_DIR / "references.json"), TABLES_DIR)

        references = [
            ref
            for ref in all_refs
            if str(ref.get("arxiv_id", "")).strip() == arxiv_id
        ]

    # Chuẩn hóa references đúng một lần.
    prepared_refs = [
        prepare_reference_record(ref)
        for ref in references
    ]

    # --------------------------------------------------------
    # Label every BibTeX entry
    # --------------------------------------------------------

    labeled_rows = []
    seen_keys = set()

    for bib in bib_entries:
        citation_key = bib.get("citation_key")

        if citation_key is None or not str(citation_key).strip():
            raise ValueError(
                f"BibTeX entry thiếu citation_key trong publication {arxiv_id}."
            )

        citation_key = str(citation_key).strip()

        if citation_key in seen_keys:
            raise ValueError(
                f"citation_key bị trùng: {citation_key} "
                f"trong publication {arxiv_id}."
            )

        seen_keys.add(citation_key)

        bib_clean = prepare_bibtex_record(bib)

        groundtruth_id = _match_one_prepared(
            bib_clean,
            prepared_refs,
        )

        labeled_rows.append({
            "citation_key": citation_key,
            "groundtruth_arxiv_id": groundtruth_id,
            # The automatic matcher must emit a binary outcome for every entry.
            # Keep the heuristic abstention reason for audit, but represent the
            # no-candidate decision separately from unresolved manual labels.
            "label_status": "match" if groundtruth_id else "auto_no_match",
            "null_reason": _auto_null_reason(bib_clean, prepared_refs) if groundtruth_id is None else None,
            "source": "auto",
        })

    # Đảm bảo không bỏ sót entry.
    if len(labeled_rows) != len(bib_entries):
        raise RuntimeError(
            f"Số label không khớp số BibTeX entries của {arxiv_id}."
        )

    return labeled_rows


def auto_label_and_save_publication(
    arxiv_id: str,
    labels_dir: Path,
    bib_entries: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> Path:
    """
    Auto label toàn bộ BibTeX entries rồi lưu JSON.
    """

    rows = auto_label_publication(
        arxiv_id=arxiv_id,
        bib_entries=bib_entries,
        references=references,
    )

    return save_labels(
        arxiv_id=arxiv_id,
        rows=rows,
        labels_dir=labels_dir,
    )


# ============================================================
# 3. READ LEGACY ZIP LABELS
# ============================================================

def load_labels_from_zip(
    zip_path: Path,
) -> dict[str, list[dict[str, Any]]]:
    """
    Đọc labels từ ZIP cũ để tương thích dữ liệu đã lưu trước đây.

    Cấu trúc ZIP:
        automatic.zip
        ├── 2310.12345.json
        ├── 2310.12346.json
        └── ...
    """

    zip_path = Path(zip_path)

    result: dict[str, list[dict[str, Any]]] = {}

    if not zip_path.exists():
        return result

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".json"):
                continue

            # Bỏ qua thư mục trong ZIP.
            if name.endswith("/"):
                continue

            rows = json.loads(
                zf.read(name).decode("utf-8-sig")
            )

            if not isinstance(rows, list):
                raise ValueError(
                    f"Dữ liệu trong {name} phải là một JSON list."
                )

            if not rows:
                continue

            arxiv_id = Path(name).stem

            if arxiv_id in result:
                raise ValueError(
                    f"Publication {arxiv_id} bị trùng trong ZIP."
                )

            result[arxiv_id] = rows

    return result


# ============================================================
# 4. LOAD ALL LABELS
# ============================================================

def load_labels(
    labels_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """
    Đọc labels từ JSON riêng lẻ:

    labels/
    ├── manual/
    │   └── {arxiv_id}.json
    └── automatic/
        └── {arxiv_id}.json

    ZIP Automatic cũ (nếu có) vẫn được đọc; JSON riêng lẻ được ưu tiên.

    Trả về:
        {
            arxiv_id: [
                {
                    "citation_key": "...",
                    "groundtruth_arxiv_id": "...",
                    "source": "manual" | "auto"
                }
            ]
        }
    """

    labels_dir = Path(labels_dir)

    result: dict[str, list[dict[str, Any]]] = {}

    if not labels_dir.exists():
        return result

    # --------------------------------------------------------
    # Load manual labels
    # --------------------------------------------------------

    manual_dir = labels_dir / "manual"

    if manual_dir.exists():
        for json_file in sorted(manual_dir.glob("*.json")):
            arxiv_id = json_file.stem

            with open(
                json_file,
                "r",
                encoding="utf-8",
            ) as f:
                rows = json.load(f)

            if not isinstance(rows, list):
                raise ValueError(
                    f"Manual label {json_file} phải là JSON list."
                )

            if rows:
                result[arxiv_id] = rows

    # --------------------------------------------------------
    # Load automatic labels from ZIP
    # --------------------------------------------------------

    auto_dir = labels_dir / "automatic"

    auto_zip = auto_dir / "automatic.zip"

    # Hỗ trợ cả vị trí ZIP cũ.
    if not auto_zip.exists():
        auto_zip = labels_dir / "automatic.zip"

    auto_labels = load_labels_from_zip(auto_zip)

    # --------------------------------------------------------
    # Load individual automatic JSON files.
    # Individual JSON overrides ZIP version.
    # --------------------------------------------------------

    if auto_dir.exists():
        for json_file in sorted(auto_dir.glob("*.json")):
            if json_file.name == "automatic.zip":
                continue

            arxiv_id = json_file.stem

            with open(
                json_file,
                "r",
                encoding="utf-8",
            ) as f:
                rows = json.load(f)

            if not isinstance(rows, list):
                raise ValueError(
                    f"Automatic label {json_file} phải là JSON list."
                )

            if rows:
                auto_labels[arxiv_id] = rows

    # --------------------------------------------------------
    # Merge manual and automatic labels.
    # Do not silently combine the same publication.
    # --------------------------------------------------------

    overlap = set(result) & set(auto_labels)

    if overlap:
        raise ValueError(
            "Publication xuất hiện trong cả manual và automatic pool: "
            + ", ".join(sorted(overlap))
        )

    result.update(auto_labels)

    return result


# ============================================================
# 6. SAVE LABELS
# ============================================================

def save_labels(
    arxiv_id: str,
    rows: list[dict[str, Any]],
    labels_dir: Path,
    to_zip_only: bool = False,
) -> Path | None:
    """
    Lưu labels theo source:

    manual -> labels/manual/{arxiv_id}.json
    auto   -> labels/automatic/{arxiv_id}.json (hoặc chỉ zip nếu to_zip_only=True)
    """

    labels_dir = Path(labels_dir)

    if not rows:
        raise ValueError(
            f"Không thể lưu danh sách label rỗng cho {arxiv_id}."
        )

    sources = {
        row.get("source")
        for row in rows
    }

    if len(sources) != 1:
        raise ValueError(
            f"Publication {arxiv_id} có nhiều source khác nhau."
        )

    source = next(iter(sources))

    if source not in ("manual", "auto"):
        raise ValueError(
            f"Source không hợp lệ: {source}."
        )

    # Validate từng row.
    seen_keys = set()

    for row in rows:
        citation_key = row.get("citation_key")

        if citation_key is None or not str(citation_key).strip():
            raise ValueError(
                f"Label của {arxiv_id} thiếu citation_key."
            )

        citation_key = str(citation_key).strip()

        if citation_key in seen_keys:
            raise ValueError(
                f"citation_key bị trùng: {citation_key}."
            )

        seen_keys.add(citation_key)

        gt_id = row.get("groundtruth_arxiv_id")

        if gt_id is not None:
            if not isinstance(gt_id, str) or not gt_id.strip():
                raise ValueError(
                    f"groundtruth_arxiv_id không hợp lệ: {gt_id}."
                )

    subfolder = (
        labels_dir / "manual"
        if source == "manual"
        else labels_dir / "automatic"
    )

    subfolder.mkdir(
        parents=True,
        exist_ok=True,
    )

    out_path = subfolder / f"{arxiv_id}.json"

    # Nếu to_zip_only=True và source="auto", không lưu file individual
    if to_zip_only and source == "auto":
        return None

    with open(
        out_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            rows,
            f,
            ensure_ascii=False,
            indent=2,
        )

    return out_path


# ============================================================
# 7. VALIDATE LABEL FORMAT
# ============================================================

def validate_label_format(
    labels: dict[str, list[dict[str, Any]]],
) -> None:
    """
    Kiểm tra cấu trúc và tính hợp lệ của toàn bộ labels.
    """

    if not labels:
        raise ValueError(
            "Chưa có dữ liệu gán nhãn nào trong thư mục labels."
        )

    for arxiv_id, rows in labels.items():
        if not isinstance(rows, list) or not rows:
            raise ValueError(
                f"Publication {arxiv_id} có danh sách label rỗng."
            )

        seen_keys = set()
        sources = set()

        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(
                    f"Label của {arxiv_id} không phải dictionary."
                )

            citation_key = row.get("citation_key")

            if citation_key is None or not str(citation_key).strip():
                raise ValueError(
                    f"Publication {arxiv_id} có label thiếu citation_key."
                )

            citation_key = str(citation_key).strip()

            if citation_key in seen_keys:
                raise ValueError(
                    f"Publication {arxiv_id} có citation_key trùng: "
                    f"{citation_key}."
                )

            seen_keys.add(citation_key)

            source = row.get("source")

            if source not in ("manual", "auto"):
                raise ValueError(
                    f"Source không hợp lệ trong {arxiv_id}: {source}."
                )

            sources.add(source)

            gt_id = row.get("groundtruth_arxiv_id")

            if gt_id is not None and (
                not isinstance(gt_id, str) or not gt_id.strip()
            ):
                raise ValueError(
                    f"groundtruth_arxiv_id không hợp lệ trong {arxiv_id}."
                )

        if len(sources) > 1:
            raise ValueError(
                f"Publication {arxiv_id} có cả manual và auto labels."
            )


# ============================================================
# 8. VALIDATE LABEL QUOTA
# ============================================================

def validate_label_quota(
    labels: dict[str, list[dict[str, Any]]],
    n_publications_total: int,
    k: int = 1,
    bibtex_counts: dict[str, int] | None = None,
    bibtex_keys: dict[str, set[str]] | None = None,
) -> None:
    """
    Kiểm tra quota theo yêu cầu M3.

    Manual:
        - >= 5 * k publications.
        - Mỗi publication >= 20 labeled entries.
        - Tổng >= 100 * k entries.

    Automatic:
        - >= 10% publications ngoài manual pool.
        - Đồng thời >= 2 * k publications.
        - Mỗi publication phải label toàn bộ BibTeX entries.

    bibtex_counts:
        Dictionary tùy chọn:
        {
            "2310.12345": 100,
            "2310.12346": 80
        }

        Nếu truyền vào, kiểm tra số auto labels có bằng
        số BibTeX entries thực tế hay không.
    """

    if k < 1:
        raise ValueError("k phải lớn hơn hoặc bằng 1.")

    if n_publications_total < 1:
        raise ValueError(
            "n_publications_total phải lớn hơn hoặc bằng 1."
        )

    validate_label_format(labels)

    # --------------------------------------------------------
    # Separate manual and automatic pools.
    # --------------------------------------------------------

    manual_papers: dict[str, int] = {}
    auto_papers: dict[str, int] = {}

    for arxiv_id, rows in labels.items():
        source = rows[0].get("source")

        if source == "manual":
            confirmed = sum(
                1 for row in rows
                if str(row.get("label_status") or ("confirmed_match" if row.get("groundtruth_arxiv_id") else "unresolved")).lower()
                in {"match", "no_match", "confirmed_match", "confirmed_no_match"}
            )
            if confirmed:
                manual_papers[arxiv_id] = confirmed

        elif source == "auto":
            auto_papers[arxiv_id] = len(rows)

    # --------------------------------------------------------
    # Check pool overlap.
    # --------------------------------------------------------

    overlap = set(manual_papers) & set(auto_papers)

    if overlap:
        raise ValueError(
            "Manual và automatic pool bị giao nhau: "
            + ", ".join(sorted(overlap))
        )

    # --------------------------------------------------------
    # Check manual publication quota.
    # --------------------------------------------------------

    n_manual = len(manual_papers)

    min_manual_required = MIN_MANUAL_PUBLICATIONS * k

    if n_manual < min_manual_required:
        raise ValueError(
            f"Thiếu manual publications: "
            f"{n_manual} < {min_manual_required} (k={k})."
        )

    # --------------------------------------------------------
    # Check minimum manual entries per publication.
    # --------------------------------------------------------

    for arxiv_id, count in manual_papers.items():
        if count < MIN_LABELED_ENTRIES_PER_MANUAL_PAPER:
            raise ValueError(
                f"Manual publication {arxiv_id} có {count} entries, "
                f"yêu cầu ít nhất "
                f"{MIN_LABELED_ENTRIES_PER_MANUAL_PAPER}."
            )

    # --------------------------------------------------------
    # Check total manual entries.
    # --------------------------------------------------------

    total_manual_entries = sum(manual_papers.values())

    min_manual_entries_required = (
        MIN_LABELED_ENTRIES_TOTAL * k
    )

    if total_manual_entries < min_manual_entries_required:
        raise ValueError(
            f"Tổng manual entries: {total_manual_entries} "
            f"< {min_manual_entries_required} (k={k})."
        )

    # --------------------------------------------------------
    # Check automatic publication quota.
    # --------------------------------------------------------

    remaining_pool = n_publications_total - n_manual

    if remaining_pool < 0:
        raise ValueError(
            "Số manual publications lớn hơn tổng số publications."
        )

    min_auto_by_fraction = math.ceil(
        MIN_AUTO_LABEL_FRACTION * remaining_pool
    )

    min_auto_by_group = 2 * k

    required_auto = max(
        min_auto_by_fraction,
        min_auto_by_group,
    )

    n_auto = len(auto_papers)

    if n_auto < required_auto:
        raise ValueError(
            f"Thiếu automatic publications: "
            f"{n_auto} < {required_auto}.\n"
            f"- Remaining publications: {remaining_pool}\n"
            f"- Required by 10% rule: {min_auto_by_fraction}\n"
            f"- Required by group size: {min_auto_by_group}\n"
            f"- k = {k}"
        )

    # --------------------------------------------------------
    # Check automatic labels cover every BibTeX entry.
    # --------------------------------------------------------

    if bibtex_counts is not None:
        for arxiv_id, label_count in auto_papers.items():
            expected_count = bibtex_counts.get(arxiv_id)

            if expected_count is None:
                raise ValueError(
                    f"Không tìm thấy BibTeX count cho auto publication "
                    f"{arxiv_id}."
                )

            if label_count != expected_count:
                raise ValueError(
                    f"Auto publication {arxiv_id}: "
                    f"{label_count}/{expected_count} entries đã được label."
                )
            if bibtex_keys is not None:
                expected_keys = bibtex_keys.get(arxiv_id)
                actual_keys = {str(row.get("citation_key", "")).strip() for row in labels[arxiv_id]}
                if expected_keys is None or actual_keys != expected_keys:
                    missing = sorted((expected_keys or set()) - actual_keys)
                    extra = sorted(actual_keys - (expected_keys or set()))
                    raise ValueError(
                        f"Auto publication {arxiv_id}: citation_key mismatch; "
                        f"missing={missing[:5]}, extra={extra[:5]}."
                    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("LABEL QUOTA VALIDATION: PASSED")
    print("--------------------------------")
    print(f"Group size (k):             {k}")
    print(f"Total publications:         {n_publications_total}")
    print(f"Manual publications:        {n_manual}")
    print(f"Manual entries:             {total_manual_entries}")
    print(f"Automatic publications:     {n_auto}")
    print(f"Remaining publications:     {remaining_pool}")
    print(f"Required automatic:         {required_auto}")
    auto_entries_total = sum(len(rows) for rows in labels.values() if rows and rows[0].get("source") == "auto")
    auto_entries_unresolved = sum(
        1
        for rows in labels.values()
        if rows and rows[0].get("source") == "auto"
        for row in rows
        if str(row.get("label_status") or "").strip().lower() == "unknown"
    )
    print(f"Automatic entries covered:  {auto_entries_total}")
    print(f"Automatic entries unknown:  {auto_entries_unresolved}")
    print("--------------------------------")
    if auto_entries_unresolved:
        print(
            "WARNING: Automatic matcher covered every listed entry, but unresolved "
            "unknown labels remain. Resolve them before claiming automatic labeling is complete."
        )
    else:
        print("All labeling requirements are satisfied.")
