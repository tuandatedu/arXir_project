"""
Hai mức dedup ACROSS VERSIONS của cùng publication.

1) Reference entries:
   - Cùng nội dung, khác citation_key → chọn 1 key, rename \\cite{} còn lại.
   - UNION field, không chọn 1 bản rồi bỏ field bản kia.
   Ví dụ: v1 vaswani2017 {title,author,year} + v2 vit_transformer {title,author,doi}
          → 1 entry key đã chọn, fields title+author+year+doi.

2) Full-text elements:
   - So khớp content SAU cleanup.
   - Trùng → cùng element_id, hierarchy version khác có thể trỏ parent khác.
"""

from __future__ import annotations

from typing import Any

from src.common.schemas import BibtexRow, ElementRow, HierarchyRow

from .hierarchy import ParseNode


def references_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """
    Quyết định 2 bib entry là cùng reference.

    Cần code bên trong (gợi ý, ghi rõ trong report):
    - DOI giống → True
    - title normalized + year + overlap authors
    - KHÔNG chỉ so citation_key (key đổi giữa version).
    """
    raise NotImplementedError("TODO(M2): references_similar")


def choose_canonical_key(keys: list[str]) -> str:
    """Chọn 1 citation_key (ví dụ key dài nhất / xuất hiện nhiều version nhất / ổn định alphabet)."""
    raise NotImplementedError("TODO(M2): choose_canonical_key")


def union_bib_fields(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Union field; giá trị non-empty thắng, conflict → ưu tiên bản có nhiều field / version mới hơn."""
    raise NotImplementedError("TODO(M2): union_bib_fields")


def dedup_bibtex_across_versions(
    per_version_entries: dict[int, list[dict[str, Any]]],
) -> tuple[list[BibtexRow], dict[str, str]]:
    """
    Input: {version: [raw entries]}.
    Output: (bibtex rows, mapping old_key → canonical_key) để rename cite nếu còn lưu tex.

    Cần code bên trong:
    - Cluster bằng references_similar (union-find).
    - Mỗi cluster: choose_canonical_key + union_bib_fields.
    """
    raise NotImplementedError("TODO(M2): dedup_bibtex_across_versions")


def flatten_tree_with_placeholders(root: ParseNode) -> list[tuple[ParseNode, ParseNode | None]]:
    """Duyệt preorder → (node, parent_node|None). Root parent = None (hierarchy đề yêu cầu parent_id non-null: tự tạo sentinel hoặc không emit cạnh root)."""
    raise NotImplementedError("TODO(M2): flatten_tree_with_placeholders")


def assign_element_ids(
    arxiv_id: str,
    trees_by_version: dict[int, ParseNode],
) -> tuple[list[ElementRow], list[HierarchyRow]]:
    """
    Dedup full-text + gán element_id = '{folder}#{discriminant}'.

    Cần code bên trong:
    - content_key = (kind, cleanup_element_content(content))
    - Lần đầu thấy → discriminant mới (s1, h1, root1, ...) + ElementRow
    - Version sau trùng content+kind → TÁI SỬ DỤNG element_id
    - Document root khác version thường khác content → root1, root2 như ví dụ đề
    - HierarchyRow mỗi cạnh (version, element_id, parent_id)
    - parent_id non-null: cạnh từ child lên parent; không emit hàng cho root
      (hoặc parent_id = element_id nếu đề bắt mọi node — chọn 1 cách, ghi README)
    """
    raise NotImplementedError("TODO(M2): assign_element_ids")
