"""
DOI resolver: Map DOI → arXiv ID để tăng coverage cho suggested_ref_arxiv_id.

Khi Semantic Scholar không tìm được arXiv ID cho một reference, nhưng reference
có DOI, ta có thể tìm arXiv ID bằng cách:
1. Xây dựng bảng DOI → arXiv ID từ bibtex.json (những bài báo đã biết)
2. Tra cứu DOI của reference để tìm arXiv ID
3. Điền vào suggested_ref_arxiv_id nếu tìm thấy

Lợi ích:
- Tăng số lượng references có suggested_ref_arxiv_id (từ M1 S2 API)
- Giảm công việc manual labeling
- Cải thiện coverage của DOI matching feature
"""

from __future__ import annotations

from typing import Any

from src.m3_matching.cleaning import normalize_doi


def build_doi_to_arxiv_map(
    bibtex_records: list[dict[str, Any]],
) -> dict[str, str]:
    """
    Xây dựng bảng: DOI (chuẩn hóa) → arXiv ID.
    
    Đầu vào: Danh sách BibTeX records từ M2 (có thể từ bibtex.json hoặc bibtex.jsonl).
    
    Trả về: Dict {doi_normalized → arxiv_id}.
    
    Ghi chú:
    - Nếu nhiều arXiv ID có cùng DOI, giữ ID đầu tiên tìm được
    - Bỏ qua records không có DOI hoặc không có arXiv ID
    """
    doi_map: dict[str, str] = {}
    
    for record in bibtex_records:
        arxiv_id = record.get("arxiv_id")
        doi = record.get("doi")
        
        if not arxiv_id or not doi:
            continue
        
        doi_norm = normalize_doi(doi)
        if not doi_norm:
            continue
        
        # Lấy ID đầu tiên (nếu có xung đột)
        if doi_norm not in doi_map:
            doi_map[doi_norm] = arxiv_id
    
    return doi_map


def resolve_arxiv_by_doi(
    doi: str | None,
    doi_map: dict[str, str],
) -> str | None:
    """
    Tra cứu arXiv ID từ DOI sử dụng bảng lookup.
    
    Đầu vào:
    - doi: DOI gốc (có thể có tiền tố https://doi.org/, chữ hoa, v.v.)
    - doi_map: Bảng DOI (chuẩn hóa) → arXiv ID
    
    Trả về: arXiv ID nếu tìm thấy, None nếu không.
    """
    if not doi:
        return None
    
    doi_norm = normalize_doi(doi)
    if not doi_norm:
        return None
    
    return doi_map.get(doi_norm)


def suggest_ref_with_doi_fallback(
    ref: dict[str, Any],
    doi_map: dict[str, str],
) -> str | None:
    """
    Lấy arXiv ID cho một reference với DOI fallback.
    
    Thứ tự ưu tiên:
    1. ref_arxiv_id_norm (từ M1 Semantic Scholar) — đã được điền
    2. DOI matching — nếu reference có DOI nhưng S2 không tìm được
    
    Đầu vào:
    - ref: Reference record (sau prepare_reference_record)
    - doi_map: Bảng DOI → arXiv ID
    
    Trả về: arXiv ID hoặc None.
    """
    # Priority 1: Semantic Scholar có tìm được không?
    if ref.get("ref_arxiv_id_norm"):
        return ref["ref_arxiv_id_norm"]
    
    # Priority 2: DOI matching
    doi = ref.get("doi_norm") or ref.get("doi")
    if doi:
        arxiv_id = resolve_arxiv_by_doi(doi, doi_map)
        if arxiv_id:
            return arxiv_id
    
    # Không tìm thấy
    return None
