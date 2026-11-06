"""
Multi-file gathering: xác định compilation path, bỏ file TeX thừa.

Root = file .tex chứa \\documentclass.
Follow \\input / \\include transitive.
Lệnh đã comment (% ...) = plain text, KHÔNG phải include.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

LOG = logging.getLogger(__name__)

_DOCUMENTCLASS_RE = re.compile(r"\\documentclass\b")
# \includegraphics must not match \include. \input@ / \inputenc similarly.
_INCLUDE_RE = re.compile(
    r"\\(input|include)(?![A-Za-z@])\s*(?:\{([^{}]+)\}|([^\s{\\%,]+))"
)
_PREFERRED_ROOT_NAMES = frozenset(
    {"main", "paper", "manuscript", "article", "root", "ms"}
)


def strip_tex_line_comments(tex_text: str) -> str:
    """
    Xóa comment TeX (từ '%' không escaped tới hết dòng).

    Cần code bên trong:
    - Không xóa \\% (percent thật).
    - Dùng cho detect include, KHÔNG nhất thiết xóa comment trước khi parse hierarchy
      (tuỳ parser; comment không phải include theo đề).
    """
    if not tex_text:
        return ""
    out: list[str] = []
    i = 0
    n = len(tex_text)
    while i < n:
        ch = tex_text[i]
        if ch == "%" and not _is_escaped(tex_text, i):
            while i < n and tex_text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_include_targets(tex_text: str) -> list[str]:
    """
    Lấy argument của \\input{...} / \\include{...} chưa bị comment.

    Cần code bên trong:
    - Regex, không match nếu '%' comment hết lệnh trên cùng dòng (đơn giản: strip comments trước).
    - \\input file   (không ngoặc) cũng hợp lệ LaTeX — cân nhắc hỗ trợ.
    - Không follow \\bibliography (bib nằm bước bibitem / .bib file).
    """
    stripped = strip_tex_line_comments(tex_text)
    targets: list[str] = []
    for match in _INCLUDE_RE.finditer(stripped):
        raw = match.group(2) if match.group(2) is not None else match.group(3)
        if not raw:
            continue
        target = raw.strip().strip("'\"")
        if not target or target.startswith("\\"):
            continue
        targets.append(target)
    return targets


def resolve_include_path(
    source_dir: Path, current_file: Path, target: str
) -> Path | None:
    """
    Map 'chapters/intro' → chapters/intro.tex nếu thiếu suffix.

    Cần code bên trong:
    - Thử target, target.tex, relative to current_file.parent rồi source_dir.
    - File không tồn tại → log warning, bỏ (không crash).
    """
    cleaned = target.strip().strip("'\"")
    if not cleaned:
        return None
    cleaned = cleaned.replace("\\", "/")
    suffix = Path(cleaned).suffix.lower()
    if suffix and suffix != ".tex":
        LOG.debug("Skip non-TeX include %s from %s", cleaned, current_file)
        return None

    bases = [Path(current_file).parent, Path(source_dir)]
    candidates: list[Path] = []
    for base in bases:
        raw = (base / cleaned).resolve()
        candidates.append(raw)
        if raw.suffix.lower() != ".tex":
            candidates.append(raw.with_suffix(raw.suffix + ".tex") if raw.suffix else raw.with_suffix(".tex"))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file() and candidate.suffix.lower() == ".tex":
            try:
                candidate.relative_to(Path(source_dir).resolve())
            except ValueError:
                LOG.warning("Include %s escapes source_dir; ignored", candidate)
                continue
            return candidate

    LOG.warning("Missing include '%s' from %s", cleaned, current_file)
    return None


def find_document_root(source_dir: Path) -> Path | None:
    """
    Tìm file chứa \\documentclass trong vN/sources.

    Cần code bên trong:
    - Scan *.tex (kể cả subfolder).
    - Bỏ qua documentclass nằm trong comment line.
    - 0 file: version empty (PDF-only) → return None, caller ghi empty parse.
    - >1 file: chọn heuristic (ít nest nhất / tên gần 'main' / file ngắn nhất path) + log.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return None

    candidates: list[Path] = []
    for tex_file in sorted(source_dir.rglob("*.tex")):
        if not tex_file.is_file():
            continue
        text = _read_tex(tex_file)
        if _DOCUMENTCLASS_RE.search(strip_tex_line_comments(text)):
            candidates.append(tex_file)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    ranked = sorted(candidates, key=lambda path: _root_score(path, source_dir))
    chosen = ranked[0]
    LOG.info(
        "Multiple \\documentclass files in %s; chose %s among %s",
        source_dir,
        chosen.relative_to(source_dir),
        [str(p.relative_to(source_dir)) for p in candidates],
    )
    return chosen


def compilation_path(source_dir: Path, root: Path | None = None) -> list[Path]:
    """
    DFS/BFS từ root, trả list file .tex theo thứ tự compile (không trùng).

    Cần code bên trong:
    - find_document_root; None → [].
    - Transitive input/include.
    - File không nằm trên path = auxiliary, IGNORE (không parse).
    """
    source_dir = Path(source_dir)
    root = root if root is not None else find_document_root(source_dir)
    if root is None:
        return []

    ordered: list[Path] = []
    visited: set[Path] = set()

    def walk(tex_file: Path) -> None:
        resolved = tex_file.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        ordered.append(resolved)
        text = _read_tex(resolved)
        for target in extract_include_targets(text):
            included = resolve_include_path(source_dir, resolved, target)
            if included is not None:
                walk(included)

    walk(root)
    return ordered


def concatenate_compilation_tex(source_dir: Path, root: Path | None = None) -> str:
    """
    Ghép nội dung các file trên compilation path (để parser 1 pass).

    Cần code bên trong:
    - Giữ nguyên thứ tự include.
    - Có thể chèn marker `% FILE: relpath` để debug, miễn parser bỏ comment.
    """
    source_dir = Path(source_dir)
    root = root if root is not None else find_document_root(source_dir)
    if root is None:
        return ""
    return _expand_file(source_dir, root, visited=set())


def _expand_file(source_dir: Path, tex_file: Path, visited: set[Path]) -> str:
    resolved = tex_file.resolve()
    if resolved in visited:
        LOG.warning("Include cycle at %s; skipping recursive expansion", resolved)
        return ""
    visited.add(resolved)
    try:
        rel = resolved.relative_to(Path(source_dir).resolve()).as_posix()
    except ValueError:
        rel = resolved.name
    try:
        return f"% FILE: {rel}\n" + _expand_includes(
            _read_tex(resolved), source_dir, resolved, visited
        )
    finally:
        visited.remove(resolved)


def _expand_includes(
    text: str,
    source_dir: Path,
    current_file: Path,
    visited: set[Path],
) -> str:
    """Replace uncommented \\input/\\include with the target file body."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "%" and not _is_escaped(text, i):
            start = i
            while i < n and text[i] != "\n":
                i += 1
            out.append(text[start:i])
            continue
        if ch == "\\" and not _is_escaped(text, i):
            match = _INCLUDE_RE.match(text, i)
            if match:
                raw = match.group(2) if match.group(2) is not None else match.group(3)
                target = (raw or "").strip().strip("'\"")
                included = resolve_include_path(source_dir, current_file, target)
                if included is not None:
                    out.append(_expand_file(source_dir, included, visited))
                i = match.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def unused_tex_files(source_dir: Path, used_paths: list[Path] | None = None) -> list[Path]:
    """Mọi .tex trong source_dir không nằm trên compilation path."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return []
    used = {p.resolve() for p in (used_paths if used_paths is not None else compilation_path(source_dir))}
    unused: list[Path] = []
    for tex_file in sorted(source_dir.rglob("*.tex")):
        if tex_file.resolve() not in used:
            unused.append(tex_file.resolve())
    return unused


def _read_tex(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    j = index - 1
    while j >= 0 and text[j] == "\\":
        slashes += 1
        j -= 1
    return slashes % 2 == 1


def _root_score(path: Path, source_dir: Path) -> tuple:
    try:
        rel = path.resolve().relative_to(Path(source_dir).resolve())
    except ValueError:
        rel = Path(path.name)
    name = path.stem.lower()
    text = strip_tex_line_comments(_read_tex(path))
    has_begin = "\\begin{document}" in text
    has_include = bool(_INCLUDE_RE.search(text))
    preferred = name in _PREFERRED_ROOT_NAMES
    return (
        0 if has_begin else 1,
        0 if preferred else 1,
        0 if has_include else 1,
        len(rel.parts),
        len(rel.as_posix()),
        rel.as_posix(),
    )
