"""
Multi-file gathering: xác định compilation path, bỏ file TeX thừa.

Root = file .tex chứa \\documentclass.
Follow \\input / \\include transitive.
Lệnh đã comment (% ...) = plain text, KHÔNG phải include.
"""

from __future__ import annotations

from pathlib import Path


def find_document_root(source_dir: Path) -> Path | None:
    """
    Tìm file chứa \\documentclass trong vN/sources.

    Cần code bên trong:
    - Scan *.tex (kể cả subfolder).
    - Bỏ qua documentclass nằm trong comment line.
    - 0 file: version empty (PDF-only) → return None, caller ghi empty parse.
    - >1 file: chọn heuristic (ít nest nhất / tên gần 'main' / file ngắn nhất path) + log.
    """
    raise NotImplementedError("TODO(M2): find_document_root")


def extract_include_targets(tex_text: str) -> list[str]:
    """
    Lấy argument của \\input{...} / \\include{...} chưa bị comment.

    Cần code bên trong:
    - Regex, không match nếu '%' comment hết lệnh trên cùng dòng (đơn giản: strip comments trước).
    - \\input file   (không ngoặc) cũng hợp lệ LaTeX — cân nhắc hỗ trợ.
    - Không follow \\bibliography (bib nằm bước bibitem / .bib file).
    """
    raise NotImplementedError("TODO(M2): extract_include_targets")


def strip_tex_line_comments(tex_text: str) -> str:
    """
    Xóa comment TeX (từ '%' không escaped tới hết dòng).

    Cần code bên trong:
    - Không xóa \\% (percent thật).
    - Dùng cho detect include, KHÔNG nhất thiết xóa comment trước khi parse hierarchy
      (tuỳ parser; comment không phải include theo đề).
    """
    raise NotImplementedError("TODO(M2): strip_tex_line_comments")


def resolve_include_path(source_dir: Path, current_file: Path, target: str) -> Path | None:
    """
    Map 'chapters/intro' → chapters/intro.tex nếu thiếu suffix.

    Cần code bên trong:
    - Thử target, target.tex, relative to current_file.parent rồi source_dir.
    - File không tồn tại → log warning, bỏ (không crash).
    """
    raise NotImplementedError("TODO(M2): resolve_include_path")


def compilation_path(source_dir: Path) -> list[Path]:
    """
    DFS/BFS từ root, trả list file .tex theo thứ tự compile (không trùng).

    Cần code bên trong:
    - find_document_root; None → [].
    - Transitive input/include.
    - File không nằm trên path = auxiliary, IGNORE (không parse).
    """
    raise NotImplementedError("TODO(M2): compilation_path")


def concatenate_compilation_tex(source_dir: Path) -> str:
    """
    Ghép nội dung các file trên compilation path (để parser 1 pass).

    Cần code bên trong:
    - Giữ nguyên thứ tự include.
    - Có thể chèn marker `% FILE: relpath` để debug, miễn parser bỏ comment.
    """
    raise NotImplementedError("TODO(M2): concatenate_compilation_tex")
