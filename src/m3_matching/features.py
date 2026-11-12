"""
Feature engineering cho cặp (bibtex entry, crawled reference) hoặc list ứng viên.

Đề cho phép dùng hierarchy M2 (ví dụ: section chứa \\cite{key}).
Mỗi feature đều có giải thích Ý TƯỞNG rõ ràng để báo cáo poster & README.
"""

from __future__ import annotations

import math
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from src.m3_matching.cleaning import (
    normalize_authors,
    normalize_doi,
    normalize_title,
    normalize_year,
    prepare_bibtex_record,
    prepare_reference_record,
)


def _extract_last_names(authors: list[str]) -> set[str]:
    """Lấy tập hợp các họ (last name) từ danh sách author chuẩn hóa."""
    lasts = set()
    for a in authors:
        if "," in a:
            last = a.split(",", 1)[0].strip()
        else:
            tokens = a.split()
            last = tokens[-1] if tokens else ""
        if last:
            lasts.add(last)
    return lasts


def title_similarity(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """
    Ý tưởng: Tiêu đề của cùng một bài báo có thể bị lệch dấu câu, viết hoa
    hoặc thứ tự từ phụ. Kết hợp token_sort_ratio và Levenshtein normalized similarity.
    Score: 0.0 .. 1.0
    """
    t1 = bib.get("title_norm") or normalize_title(bib.get("title") or "")
    t2 = ref.get("title_norm") or normalize_title(ref.get("ref_title") or ref.get("title") or "")
    if not t1 or not t2:
        return 0.0
    # rapidfuzz fuzz.token_sort_ratio trả về 0..100
    sort_score = fuzz.token_sort_ratio(t1, t2) / 100.0
    lev_score = Levenshtein.normalized_similarity(t1, t2)
    return max(sort_score, lev_score)


def author_overlap(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """
    Ý tưởng: Cùng một bài báo thì danh sách tác giả (đặc biệt là họ) phải trùng khớp.
    Tính Jaccard similarity trên tập các họ (last names) của 2 tài liệu.
    Score: 0.0 .. 1.0
    """
    a1 = bib.get("authors_norm") or normalize_authors(bib.get("authors") or [])
    a2 = ref.get("authors_norm") or normalize_authors(ref.get("ref_authors") or ref.get("authors") or [])
    lasts1 = _extract_last_names(a1)
    lasts2 = _extract_last_names(a2)
    if not lasts1 or not lasts2:
        return 0.0
    intersection = lasts1 & lasts2
    union = lasts1 | lasts2
    return len(intersection) / len(union) if union else 0.0


def year_distance(bib: dict[str, Any], ref: dict[str, Any]) -> float:
    """
    Ý tưởng: Các tài liệu trùng nhau thường có năm công bố giống nhau hoặc
    lệch 1 năm (do năm preprint trên arXiv khác năm xuất bản kỷ yếu/tạp chí).
    Nếu chênh lệch nhiều năm -> hầu như chắc chắn là false positive.
    Nếu thiếu năm -> gán giá trị sentinel -1.0.
    """
    y1 = bib.get("year_norm") if "year_norm" in bib else normalize_year(bib.get("year"))
    y2 = ref.get("year_norm") if "year_norm" in ref else normalize_year(ref.get("ref_submission_date") or ref.get("year"))
    if y1 is None or y2 is None:
        return -1.0
    return float(abs(y1 - y2))


def cite_context_features(arxiv_id: str, citation_key: str, context_map: dict | None = None) -> dict[str, float]:
    """
    Ý tưởng: Tần suất và vị trí trích dẫn của citation_key trong văn bản (M2).
    Một tài liệu được trích dẫn nhiều lần hoặc xuất hiện ở phần References chính
    sẽ có ý nghĩa xác thực cao hơn.
    """
    if context_map and citation_key in context_map:
        return context_map[citation_key]
    return {
        "cite_count": 0.0,
        "is_cited_in_text": 0.0,
    }


def feature_names() -> list[str]:
    """
    Danh sách tên cột đặc trưng khớp hoàn toàn với vector trả về của pair_feature_vector.
    Bắt buộc đồng bộ để đưa vào DataFrame / model training và báo cáo poster.
    """
    return [
        "title_levenshtein",      # Levenshtein distance tương đối (0..1)
        "title_token_sort",       # Token sort ratio (xử lý đảo từ) (0..1)
        "title_token_set",        # Token set ratio (xử lý substring/phần mở rộng) (0..1)
        "title_jaccard",          # Jaccard từ vựng giữa 2 tiêu đề (0..1)
        "title_exact",            # 1.0 nếu tiêu đề trùng khớp hoàn toàn, 0.0 nếu khác
        "title_len_diff_ratio",   # Độ lệch chiều dài tiêu đề (|len1 - len2| / max(len1, len2))
        "author_jaccard",         # Jaccard overlap trên họ của các tác giả (0..1)
        "author_first_match",     # 1.0 nếu tác giả đầu tiên trùng họ, 0.0 nếu không
        "author_any_match",       # 1.0 nếu có ít nhất 1 tác giả trùng họ, 0.0 nếu không
        "year_diff",              # Hiệu số năm tuyệt đối (|y1 - y2|), nếu thiếu gán 99.0
        "year_exact",             # 1.0 nếu cùng năm, 0.0 nếu khác, -1.0 nếu thiếu năm
        "year_missing",           # 1.0 nếu một trong hai tài liệu thiếu năm, 0.0 nếu đủ
        "doi_match",              # 1.0 nếu DOI trùng, -1.0 nếu cả 2 có DOI nhưng khác, 0.0 nếu thiếu
        "cite_count",             # Số lần citation_key được cite trong bài báo
    ]


def pair_feature_vector(
    bib: dict[str, Any],
    ref: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> list[float]:
    """
    Ghép mọi đặc trưng thành vector số cố định (float) cho cặp (bib, ref).
    Vector này được Người 2 đưa trực tiếp vào mô hình phân loại / ranking.
    """
    # 1. Chuẩn hóa nếu chưa chuẩn hóa
    t1 = bib.get("title_norm")
    if t1 is None:
        t1 = normalize_title(bib.get("title") or "")
    t2 = ref.get("title_norm")
    if t2 is None:
        t2 = normalize_title(ref.get("ref_title") or ref.get("title") or "")

    a1 = bib.get("authors_norm")
    if a1 is None:
        a1 = normalize_authors(bib.get("authors") or [])
    a2 = ref.get("authors_norm")
    if a2 is None:
        a2 = normalize_authors(ref.get("ref_authors") or ref.get("authors") or [])

    y1 = bib.get("year_norm") if "year_norm" in bib else normalize_year(bib.get("year"))
    y2 = ref.get("year_norm") if "year_norm" in ref else normalize_year(ref.get("ref_submission_date") or ref.get("year"))

    # 2. Đặc trưng tiêu đề
    if t1 and t2:
        f_lev = float(Levenshtein.normalized_similarity(t1, t2))
        f_token_sort = float(fuzz.token_sort_ratio(t1, t2) / 100.0)
        f_token_set = float(fuzz.token_set_ratio(t1, t2) / 100.0)
        words1, words2 = set(t1.split()), set(t2.split())
        f_jaccard = float(len(words1 & words2) / len(words1 | words2)) if (words1 or words2) else 0.0
        f_exact = 1.0 if t1 == t2 else 0.0
        max_len = max(len(t1), len(t2))
        f_len_diff = float(abs(len(t1) - len(t2)) / max_len) if max_len > 0 else 0.0
    else:
        f_lev = f_token_sort = f_token_set = f_jaccard = f_exact = 0.0
        f_len_diff = 1.0

    # 3. Đặc trưng tác giả
    lasts1 = _extract_last_names(a1)
    lasts2 = _extract_last_names(a2)
    # Tác giả đầu tiên từ list gốc (không phải random từ set)
    first1 = a1[0].split(",")[0] if a1 else ""  # Lấy phần trước "," hoặc toàn bộ
    first2 = a2[0].split(",")[0] if a2 else ""
    
    if lasts1 and lasts2:
        f_author_jaccard = float(len(lasts1 & lasts2) / len(lasts1 | lasts2))
        f_author_any = 1.0 if bool(lasts1 & lasts2) else 0.0
        f_author_first = 1.0 if (first1 and first1 == first2) else 0.0
    else:
        f_author_jaccard = f_author_any = f_author_first = 0.0

    # 4. Đặc trưng năm công bố
    if y1 is not None and y2 is not None:
        f_year_diff = float(abs(y1 - y2))
        f_year_exact = 1.0 if y1 == y2 else 0.0
        f_year_missing = 0.0
    else:
        f_year_diff = 99.0
        f_year_exact = -1.0
        f_year_missing = 1.0

    # 5. Đặc trưng DOI (luôn so trên dạng đã chuẩn hóa)
    doi1 = bib.get("doi_norm") or normalize_doi(bib.get("doi"))
    doi2 = ref.get("doi_norm") or normalize_doi(
        ref.get("doi") or ref.get("ref_doi") or ref.get("DOI")
    )
    if not doi2 and isinstance(ref.get("externalIds"), dict):
        doi2 = normalize_doi(ref["externalIds"].get("DOI"))
    if doi1 and doi2:
        f_doi_match = 1.0 if doi1 == doi2 else -1.0
    else:
        f_doi_match = 0.0

    # 6. Ngữ cảnh (M2)
    f_cite_count = float(extra.get("cite_count", 0.0)) if extra else 0.0

    return [
        f_lev,
        f_token_sort,
        f_token_set,
        f_jaccard,
        f_exact,
        f_len_diff,
        f_author_jaccard,
        f_author_first,
        f_author_any,
        f_year_diff,
        f_year_exact,
        f_year_missing,
        f_doi_match,
        f_cite_count,
    ]
