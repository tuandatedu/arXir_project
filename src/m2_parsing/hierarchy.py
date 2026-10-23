"""
Parse LaTeX → cây phân cấp / version.

Root = Document.
Level 2 điển hình = chapter/section.
Parser TỰ suy level từ lệnh (\\chapter, \\section, \\subsection, \\paragraph, ...).

Leaf bắt buộc:
- sentence (prose, chấm câu)
- block formula (equation / $$...$$)
- figure (kể cả table = figure)

itemize/enumerate: list = node cha, mỗi \\item = list_item con, rồi sentence bên trong.

Loại trừ: References section KHÔNG vào hierarchy.
Bắt buộc gồm: Acknowledgements, Appendices (kể cả \\section*).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParseNode:
    """Node tạm trong cây 1 version (trước khi gán element_id / dedup)."""

    kind: str
    content: str
    children: list["ParseNode"] = field(default_factory=list)
    source_hint: str = ""  # ví dụ 'section:Introduction'


def heading_level(command: str) -> int | None:
    """
    Map lệnh heading → độ sâu. None nếu không phải heading.

    Cần code bên trong (gợi ý):
    - part=1, chapter=2, section=3, subsection=4, subsubsection=5, paragraph=6, subparagraph=7
    - starred forms (\\section*) cùng level.
    """
    raise NotImplementedError("TODO(M2): heading_level")


def is_references_heading(title: str) -> bool:
    """True nếu section là bibliography/references → skip cả subtree."""
    raise NotImplementedError("TODO(M2): is_references_heading")


def is_acknowledgement_or_appendix(title: str, command: str) -> str | None:
    """
    Trả 'acknowledgement' / 'appendix' / None.

    Cần code bên trong: match appendix, acknowledgement(s); \\appendix switch của LaTeX.
    """
    raise NotImplementedError("TODO(M2): is_acknowledgement_or_appendix")


def split_sentences(prose: str) -> list[str]:
    """
    Tách sentence leaves. DẤU CHẤM không phải hết câu thì KHÔNG tách:

    Cần code bên trong — không split bên trong:
    - toán (inline $...$ đã chuẩn hóa)
    - lệnh LaTeX
    - viết tắt i.e. / e.g. / et al. / Fig. 1 / Eq. / Dr.
    - URL
    - số thập phân 3.14
    """
    raise NotImplementedError("TODO(M2): split_sentences")


def parse_tex_to_tree(tex: str) -> ParseNode:
    """
    Parser chính: tex đã concat + (nên) đã cleanup/normalize math.

    Cần code bên trong:
    - Root kind='document'
    - Walk token/environment: heading, itemize, equation, figure, table, thebibliography (skip)
    - Prose → paragraph → sentence leaves
    - Empty tex → root rỗng (version empty, vẫn record)
    """
    raise NotImplementedError("TODO(M2): parse_tex_to_tree")
