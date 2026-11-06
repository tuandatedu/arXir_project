"""
Multi-file gathering: xác định compilation path, bỏ file TeX thừa.

Root = file .tex chứa \\documentclass.
Follow \\input / \\include transitive.
Lệnh đã comment (% ...) = plain text, KHÔNG phải include.
"""

from __future__ import annotations

import logging
import json
import re
from difflib import SequenceMatcher
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




def active_tex(tex_text: str, initial_flags: dict[str, bool] | None = None) -> str:
    """Mask TeX comments and demonstrably inactive conditional branches.

    Keeps newlines and character positions. Handles literal iftrue/iffalse,
    \\newif\\ifflag plus \\flagtrue/\\flagfalse, and locally defined
    \\ifdefined\\macro. Unknown conditions are deliberately preserved rather
    than guessing which branch the TeX engine will compile.
    """
    if not tex_text:
        return ""
    flags: dict[str, bool] = dict(initial_flags or {})
    defined: set[str] = set()
    frames: list[tuple[bool, bool | None, bool]] = []  # parent active, condition, else branch
    active = True
    output: list[str] = []
    i, n = 0, len(tex_text)

    def emit(segment: str, visible: bool) -> None:
        output.append(segment if visible else ''.join('\n' if c == '\n' else ' ' for c in segment))

    while i < n:
        if tex_text[i] == '%' and not _is_escaped(tex_text, i):
            end = tex_text.find('\n', i)
            end = n if end < 0 else end
            emit(tex_text[i:end], False)
            i = end
            continue
        if tex_text[i] not in '%\\':
            # Copy long prose spans in one operation; per-character processing
            # is needlessly expensive on multi-megabyte arXiv sources.
            next_escape = tex_text.find('\\', i)
            next_comment = tex_text.find('%', i)
            next_positions = [v for v in (next_escape, next_comment) if v >= 0]
            end = min(next_positions) if next_positions else n
            emit(tex_text[i:end], active)
            i = end
            continue
        if tex_text[i] != '\\' or _is_escaped(tex_text, i):
            emit(tex_text[i], active)
            i += 1
            continue
        match = re.compile(r'\\([A-Za-z@]+)').match(tex_text, i)
        if not match:
            emit(tex_text[i], active)
            i += 1
            continue
        name = match[1]
        end = match.end()
        if name == 'newif':
            found = re.compile(r'\s*\\if([A-Za-z@]+)').match(tex_text, end)
            if found:
                if active:
                    flags[found[1]] = False
                end = found.end()
                emit(tex_text[i:end], False)
                i = end
                continue
        if name in {'def', 'gdef', 'edef', 'xdef'}:
            found = re.compile(r'\s*\\([A-Za-z@]+)').match(tex_text, end)
            if active and found:
                defined.add(found[1])
        if name.endswith('true') and name[:-4] in flags and active:
            flags[name[:-4]] = True
        if name.endswith('false') and name[:-5] in flags and active:
            flags[name[:-5]] = False
        cond: bool | None = None
        conditional = False
        if name == 'iftrue':
            cond, conditional = True, True
        elif name == 'iffalse':
            cond, conditional = False, True
        elif name == 'ifdefined':
            conditional = True
            found = re.compile(r'\s*\\([A-Za-z@]+)').match(tex_text, end)
            if found:
                # Only decide if this macro is locally defined; an unknown macro
                # may be defined in a package or preamble we have not expanded.
                cond = True if found[1] in defined else None
                end = found.end()
        elif name.startswith('if') and len(name) > 2:
            conditional = True
            if name[2:] in flags:
                cond = flags[name[2:]]
        if conditional:
            frames.append((active, cond, False))
            active = active and cond is not False
            emit(tex_text[i:end], False)
            i = end
            continue
        if name == 'else' and frames:
            parent, cond, _ = frames[-1]
            frames[-1] = (parent, cond, True)
            active = parent and cond is not True
            emit(tex_text[i:end], False)
            i = end
            continue
        if name == 'fi' and frames:
            parent, _, _ = frames.pop()
            active = parent
            emit(tex_text[i:end], False)
            i = end
            continue
        emit(tex_text[i:end], active)
        i = end
    if initial_flags is not None:
        initial_flags.update(flags)
    return ''.join(output)


def extract_include_targets(tex_text: str, flags: dict[str, bool] | None = None) -> list[str]:
    """
    Lấy argument của \\input{...} / \\include{...} chưa bị comment.

    Cần code bên trong:
    - Regex, không match nếu '%' comment hết lệnh trên cùng dòng (đơn giản: strip comments trước).
    - \\input file   (không ngoặc) cũng hợp lệ LaTeX — cân nhắc hỗ trợ.
    - Không follow \\bibliography (bib nằm bước bibitem / .bib file).
    """
    stripped = active_tex(tex_text, initial_flags=flags)
    targets: list[str] = []
    for match in _INCLUDE_RE.finditer(stripped):
        # Regex may begin at the second backslash of TeX's line-break
        # command \\input (meaning: \\ + ordinary text "input").
        # Such a backslash is escaped and cannot begin a real include.
        if _is_escaped(stripped, match.start()):
            continue
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


def compilation_path(source_dir: Path, root: Path | None = None,
                     missing: list[str] | None = None) -> list[Path]:
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
    flags: dict[str, bool] = {}
    active_tex(_read_tex(root), initial_flags=flags)

    def walk(tex_file: Path) -> None:
        resolved = tex_file.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        ordered.append(resolved)
        text = _read_tex(resolved)
        for target in extract_include_targets(text, flags=flags):
            included = resolve_include_path(source_dir, resolved, target)
            if included is not None:
                walk(included)
            elif missing is not None and Path(target).suffix.lower() in {"", ".tex"}:
                missing.append(f"{_relative_source_path(source_dir, resolved)}: {target}")

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
    flags: dict[str, bool] = {}
    active_tex(_read_tex(root), initial_flags=flags)
    return _expand_file(source_dir, root, visited=set(), flags=flags)


def _expand_file(source_dir: Path, tex_file: Path, visited: set[Path],
                 flags: dict[str, bool]) -> str:
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
            active_tex(_read_tex(resolved), initial_flags=flags), source_dir, resolved, visited, flags
        )
    finally:
        visited.remove(resolved)


def _expand_includes(
    text: str,
    source_dir: Path,
    current_file: Path,
    visited: set[Path],
    flags: dict[str, bool],
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
                    out.append(_expand_file(source_dir, included, visited, flags))
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


def _relative_source_path(source_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(source_dir).as_posix()
    except ValueError:
        return path.name


def _title_words(text: str) -> str:
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE)
    return " ".join(text.split())


def _root_score(path: Path, source_dir: Path) -> tuple:
    """Rank primary manuscripts above supplementary standalone TeX documents.

    Use M1 metadata title when available; do not rely on filename length.
    """
    try:
        rel = path.resolve().relative_to(Path(source_dir).resolve())
    except ValueError:
        rel = Path(path.name)
    name = path.stem.lower()
    tex = strip_tex_line_comments(_read_tex(path))
    title_match = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", tex)
    title = ""
    if title_match:
        depth, offset = 1, title_match.end()
        end = offset
        while end < len(tex) and depth:
            if tex[end] == "{" and not _is_escaped(tex, end):
                depth += 1
            elif tex[end] == "}" and not _is_escaped(tex, end):
                depth -= 1
            end += 1
        title = tex[offset : end - 1] if depth == 0 else ""
    metadata = Path(source_dir).parent.parent / 'paper.json'
    paper_title = ''
    if metadata.is_file():
        try:
            paper_title = json.loads(metadata.read_text(encoding='utf-8')).get('title', '')
        except (OSError, ValueError, AttributeError):
            pass
    title_score = SequenceMatcher(None, _title_words(title), _title_words(paper_title)).ratio() if title and paper_title else 0.0
    is_supp = bool(re.search(r"supp(?:lement(?:ary|al)?)?|appendix|(^|[_-])si($|[_-])", name, re.I))
    is_supp |= bool(re.match(r"\s*(?:supplement(?:ary|al)?|appendix)\b", _title_words(title)))
    has_begin = r"\begin{document}" in tex
    return (
        -round(title_score, 4) if paper_title and title else 0,
        int(is_supp),
        0 if name in _PREFERRED_ROOT_NAMES or name.startswith('main') else 1,
        0 if has_begin else 1,
        0 if _INCLUDE_RE.search(tex) else 1,
        len(rel.parts),
        rel.as_posix(),
    )
