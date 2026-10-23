"""
Cleanup + math normalization TRƯỚC full-text dedup.

- Bỏ lệnh formatting không semantic: \\centering, [htpb] placement, \\midrule, ...
- Inline math → $...$
- Block math → \\begin{equation}...\\end{equation}
- KHÔNG xóa figure env / \\includegraphics (cấu trúc M2 cần).
"""

from __future__ import annotations


def remove_non_semantic_commands(tex: str) -> str:
    """
    Gỡ clutter formatting.

    Cần code bên trong (tối thiểu theo đề):
    - \\centering, \\hfill, \\vspace, \\hspace, \\newpage, \\clearpage
    - optional args placement [htbp] / [H] trên figure/table
    - \\hline, \\toprule, \\midrule, \\bottomrule
    - \\maketitle / \\tableofcontents nếu không chứa nội dung
    - Collapse whitespace sau khi xóa (để full-text match ổn định)
    """
    raise NotImplementedError("TODO(M2): remove_non_semantic_commands")


def normalize_inline_math(tex: str) -> str:
    """
    \\(...\\), \\begin{math}, \\ensuremath → $...$

    Cần code bên trong: không đụng block math; cẩn thận nested.
    """
    raise NotImplementedError("TODO(M2): normalize_inline_math")


def normalize_block_math(tex: str) -> str:
    """
    $$, \\[...\\], equation*, align, gather, displaymath → equation env thống nhất.

    Cần code bên trong:
    - Giữ body toán, chỉ đổi wrapper.
    - align nhiều dòng: có thể giữ nguyên env HOẶC bọc equation + comment trong report.
      Đề gợi ý equation; nếu giữ align thì ghi rõ trong Jupyter Book.
    """
    raise NotImplementedError("TODO(M2): normalize_block_math")


def cleanup_element_content(content: str) -> str:
    """
    Cleanup 1 node (heading/sentence/formula/figure) trước khi so khớp full-text.

    Cần code bên trong:
    - strip, normalize space, unicode dash/quote nếu cần.
    - Công thức đã unified thì so khớp chuỗi sau bước này.
    """
    raise NotImplementedError("TODO(M2): cleanup_element_content")


def cleanup_document(tex: str) -> str:
    """Pipeline: non-semantic → inline math → block math."""
    raise NotImplementedError("TODO(M2): cleanup_document")
