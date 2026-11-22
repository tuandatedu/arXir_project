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
# Common packages: import.sty, subfiles.sty, and inputfrom.sty. Only literal
# two-argument forms are expanded; macro-computed names remain unsupported.
_IMPORT_RE = re.compile(
    r"\\(?:import|subimport|inputfrom|subinputfrom|includefrom|subincludefrom)"
    r"(?![A-Za-z@])\s*\{([^{}]+)\}\s*\{([^{}]+)\}"
)
_SUBFILE_RE = re.compile(r"\\subfile(?![A-Za-z@])\s*\{([^{}]+)\}")
_INCLUDE_ANY_RE = re.compile(
    _IMPORT_RE.pattern + "|" + _SUBFILE_RE.pattern + "|" + _INCLUDE_RE.pattern
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




_LITERAL_ENV_RE = re.compile(
    r"\\begin\s*\{(filecontents\*?|verbatim\*?|Verbatim|lstlisting|minted|comment)\}"
    r"(?:\s*\{[^{}]*\})?"
)
_INLINE_VERB_RE = re.compile(r"\\verb\*?(?![A-Za-z@])")


def _mask_filecontents_environments(tex_text: str) -> str:
    """Mask literal/code environments and inline verbatim, including TeX examples.

    Preserve lengths and newlines for source position stability. Escaped TeX
    snippets inside listings are not actual include commands or documents.
    """
    def mask(span: str) -> str:
        return ''.join('\n' if ch == '\n' else ' ' for ch in span)

    spans: list[tuple[int, int]] = []
    offset = 0
    while match := _LITERAL_ENV_RE.search(tex_text, offset):
        line_start = tex_text.rfind('\n', 0, match.start()) + 1
        prefix = tex_text[line_start:match.start()]
        if any(ch == '%' and not _is_escaped(prefix, pos)
               for pos, ch in enumerate(prefix)):
            offset = match.end()
            continue
        end_pattern = re.compile(r"\\end\s*\{" + re.escape(match[1]) + r"\}")
        end = end_pattern.search(tex_text, match.end())
        if end is None:
            offset = match.end()  # never blank malformed paper remainder
            continue
        spans.append((match.start(), end.end()))
        offset = end.end()
    # Inline \verb|\input{fake}|. Its delimiter is an arbitrary nonletter.
    for verb in _INLINE_VERB_RE.finditer(tex_text):
        begin = verb.end()
        if begin >= len(tex_text) or tex_text[begin].isspace():
            continue
        delim = tex_text[begin]
        end = tex_text.find(delim, begin + 1)
        if end < 0 or '\n' in tex_text[begin:end]:
            continue
        if any(lo <= verb.start() < hi for lo, hi in spans):
            continue
        line_start = tex_text.rfind('\n', 0, verb.start()) + 1
        prefix = tex_text[line_start:verb.start()]
        if any(ch == '%' and not _is_escaped(prefix, pos)
               for pos, ch in enumerate(prefix)):
            continue
        spans.append((verb.start(), end + 1))
    if not spans:
        return tex_text
    output: list[str] = []
    previous = 0
    for begin, end in sorted(spans):
        if begin < previous:
            continue
        output.extend((tex_text[previous:begin], mask(tex_text[begin:end])))
        previous = end
    output.append(tex_text[previous:])
    return ''.join(output)


def _include_target(match: re.Match) -> str:
    """Normalize the known static include syntaxes into one relative target."""
    if match.group(1) is not None and match.group(2) is not None:
        directory, name = match.group(1), match.group(2)
        return directory.rstrip('/\\') + '/' + name.lstrip('/\\')
    if match.group(3) is not None:
        return match.group(3).strip()
    return (match.group(5) if match.group(5) is not None else match.group(6) or '').strip()


def _include_calls(visible: str):
    """Iterate actual include commands (not escaped or parameter placeholders)."""
    for match in _INCLUDE_ANY_RE.finditer(visible):
        if _is_escaped(visible, match.start()):
            continue
        target = _include_target(match).strip().strip("'\"")
        if not target or target.startswith(("\\", "#")) or '#' in target:
            continue
        yield match, target


def active_tex(tex_text: str, initial_flags: dict[str, bool] | None = None) -> str:
    """Mask TeX comments and demonstrably inactive conditional branches.

    Keeps newlines and character positions. Handles literal iftrue/iffalse,
    \\newif\\ifflag plus \\flagtrue/\\flagfalse, and locally defined
    \\ifdefined\\macro. Unknown conditions are deliberately preserved rather
    than guessing which branch the TeX engine will compile.
    """
    if not tex_text:
        return ""
    tex_text = _mask_filecontents_environments(tex_text)
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
    return [target for _, target in _include_calls(stripped)]


def _balanced_tex_group(text: str, opening_brace: int) -> tuple[str, int] | None:
    """Return the inside of a balanced braced TeX group and the end offset."""
    if opening_brace >= len(text) or text[opening_brace] != "{":
        return None
    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{" and not _is_escaped(text, index):
            depth += 1
        elif text[index] == "}" and not _is_escaped(text, index):
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1:index], index + 1
    return None


_INPUT_PATH_DEF_RE = re.compile(
    r"\\(?:def|gdef|edef|xdef)\s*\\input@path\s*\{"
    r"|\\(?:newcommand|renewcommand|providecommand)\*?\s*"
    r"(?:\{\s*\\input@path\s*\}|\\input@path)\s*"
    r"(?:\[[^\]]*\]\s*)?\{"
)


def extract_input_search_paths(tex_text: str) -> list[str]:
    """Read literal ``\\input@path`` directories (not a full TeX interpreter).

    Supports the common ``\\def\\input@path{{content/}{sections/}}`` and
    ``\\newcommand{\\input@path}{{content/}}`` spellings. Dynamic TeX macros
    are deliberately skipped rather than inventing a filesystem location.
    """
    visible = active_tex(tex_text)
    paths: list[str] = []
    for match in _INPUT_PATH_DEF_RE.finditer(visible):
        parsed = _balanced_tex_group(visible, match.end() - 1)
        if parsed is None:
            continue
        body, _ = parsed
        items = re.findall(r"\{([^{}]*)\}", body)
        if not items and body.strip():
            items = [body]
        for raw in items:
            value = raw.strip().replace("\\", "/")
            if (not value or value.startswith("/") or
                    re.search(r"[\\{}#%$]", value) or value in paths):
                continue
            paths.append(value)
    return paths


def _case_insensitive_unique_file(candidate: Path, source_dir: Path) -> Path | None:
    """Recover a *unique* case mismatch without guessing among duplicates."""
    source_root = Path(source_dir).resolve()
    try:
        parts = candidate.relative_to(source_root).parts
    except ValueError:
        return None
    matches = [source_root]
    for part in parts:
        next_matches: list[Path] = []
        for directory in matches:
            if not directory.is_dir():
                continue
            try:
                next_matches.extend(
                    child for child in directory.iterdir()
                    if child.name.casefold() == part.casefold()
                )
            except OSError:
                continue
        matches = next_matches
        if not matches or len(matches) > 1:
            if len(matches) > 1:
                LOG.warning("Ambiguous case-insensitive include: %s", candidate)
            return None
    if len(matches) != 1 or not matches[0].is_file():
        return None
    result = matches[0].resolve()
    try:
        result.relative_to(source_root)
    except ValueError:
        return None
    return result if result.suffix.lower() == ".tex" else None


def resolve_include_path(
    source_dir: Path, current_file: Path, target: str,
    search_paths: list[str] | None = None,
) -> Path | None:
    """Resolve literal TeX includes, with ``\\input@path`` and a safe case fallback.

    Exact spellings take precedence globally. Case-insensitive recovery is used
    only when exactly one matching path exists across all search bases.
    No file outside ``source_dir`` is allowed, including symlink targets.
    """
    cleaned = target.strip().strip("'\"").replace("\\", "/")
    if not cleaned or Path(cleaned).is_absolute():
        return None
    suffix = Path(cleaned).suffix.lower()
    non_tex_suffixes = {".sty", ".cls", ".bib", ".bbl", ".aux", ".png",
                        ".jpeg", ".jpg", ".pdf", ".eps", ".ps", ".svg", ".cfg", ".def"}
    if suffix in non_tex_suffixes:
        LOG.debug("Skip non-TeX include %s from %s", cleaned, current_file)
        return None

    root = Path(source_dir).resolve()
    current = Path(current_file).resolve()
    bases: list[Path] = [current.parent, root]
    for raw_path in search_paths or []:
        if Path(raw_path).is_absolute():
            continue
        # input@path is normally evaluated from the compilation directory.
        # Also try the active file directory for nested standalone sources.
        bases.extend((root / raw_path, current.parent / raw_path))

    candidates: list[Path] = []
    seen: set[Path] = set()
    for base in bases:
        raw = (base / cleaned).absolute()
        variants = [raw]
        if raw.suffix.lower() != ".tex":
            variants.append(Path(str(raw) + ".tex"))
        for candidate in variants:
            # Normalize .. but do not leave the extracted archive.
            candidate = candidate.resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                candidate.relative_to(root)
            except ValueError:
                LOG.debug("Include path outside source tree ignored: %s", candidate)
                continue
            candidates.append(candidate)
            if candidate.is_file() and candidate.suffix.lower() == ".tex":
                return candidate

    recovered: set[Path] = set()
    for candidate in candidates:
        match = _case_insensitive_unique_file(candidate, root)
        if match is not None:
            recovered.add(match)
    if len(recovered) == 1:
        chosen = next(iter(recovered))
        LOG.info("Recovered include case mismatch '%s' -> %s", cleaned,
                 chosen.relative_to(root))
        return chosen
    if len(recovered) > 1:
        LOG.warning("Ambiguous case-insensitive include '%s' from %s: %s",
                    cleaned, current_file, sorted(str(p) for p in recovered))
        return None
    LOG.warning("Missing include '%s' from %s", cleaned, current_file)
    return None




# Plain TeX papers use \magnification, \font, \bye instead of \documentclass.
# Requiring both a TeX setup command and the end marker prevents accidental
# promotion of arbitrary macros, aux files, or partial manuscripts to roots.
_PLAIN_START_RE = re.compile(r"\\(?:magnification|font)\b")
_PLAIN_END_RE = re.compile(r"\\bye\b")


def is_plain_tex_document(tex_text: str) -> bool:
    visible = strip_tex_line_comments(tex_text)
    return bool(_PLAIN_START_RE.search(visible) and _PLAIN_END_RE.search(visible)
                and len(visible) >= 1000 and not _DOCUMENTCLASS_RE.search(visible))


def prepare_plain_tex_for_parsing(tex_text: str) -> str:
    """Conservatively adapt a *complete* Plain TeX paper for the tree parser.

    Discards macro/font preamble, anything after \bye and bibliography section;
    converts only recognizable heading forms, preserving math and prose.
    This is a text-structure adapter, NOT a full Plain TeX interpreter.
    """
    visible = strip_tex_line_comments(tex_text)
    end = _PLAIN_END_RE.search(visible)
    if end:
        visible = visible[:end.start()]
    title = re.search(
        r"(?m)^\s*\\(?:hopp|hoppp)\s*\n\s*\{\\bigbf\s+", visible
    )
    if title is None:
        title = re.search(r"\\centerline\s*\{\\(?:bigbf|bf)\b", visible)
    if title is None:
        title = re.search(r"\\centerline\s*\{", visible)
    if title:
        visible = visible[title.start():]
    else:
        head = re.search(r"\\(?:section|subsection)\s*(?:\{|\\centerline)", visible)
        if head:
            visible = visible[head.start():]
    # Bibliography is handled separately by BibTeX extraction, not hierarchy.
    refs = re.search(
        r"\\centerline\s*\{\\bf\s+References\s*\}|"
        r"(?:^|\n)\s*(?:\\hoppp|\\bigskip|\\medskip)?\s*"
        r"\{\\bf\s+References\s*\}", visible, re.I
    )
    if refs:
        visible = visible[:refs.start()]

    # Plain TeX heading conventions: \section \centerline{\bf X}.
    visible = re.sub(
        r"\\section\s*\\centerline\s*\{\\(?:bf|bigbf)\s+([^{}\n]+)\}",
        lambda m: r"\section{" + m[1].strip() + "}", visible
    )
    # Plain TeX uses {\bf 3. Heading} on a line after \bigskip.
    visible = re.sub(
        r"(?m)^\s*\{\\(?:bf|bigbf)\s+((?:\d+[.]\s+)[^{}\n]{2,110})\}",
        lambda m: r"\section{" + m[1].strip() + "}", visible
    )
    # Non-numbered Plain TeX heading convention (after title/abstract).
    visible = re.sub(
        r"\\hoppp\s*\{\\bf\s+([^{}\n]+)\}",
        lambda m: r"\section{" + m[1].strip() + "}", visible
    )
    # A custom \subsection macro commonly contains the heading in a brace.
    visible = re.sub(
        r"\\subsection\s*\{\\(?:csc|bf)\s+([^{}\n]+)\}",
        lambda m: r"\subsection{" + m[1].strip() + "}", visible
    )
    return visible


def find_plain_tex_root(source_dir: Path) -> Path | None:
    """Find a plausible complete Plain TeX driver if no LaTeX root exists."""
    source_dir = Path(source_dir)
    candidates = []
    for path in sorted(source_dir.rglob('*')):
        if path.is_file() and path.suffix.lower() == '.tex':
            raw = _read_tex(path)
            if is_plain_tex_document(raw):
                content = prepare_plain_tex_for_parsing(raw)
                # Require actual prose; a macro/package file containing \bye
                # must not appear as an empty but "parsed" publication.
                if len(content.strip()) >= 250 and re.search(r'[A-Za-z]{4,}\s+[A-Za-z]{4,}', content):
                    candidates.append(path)
    if not candidates:
        return None
    return min(candidates, key=lambda path: _root_score(path, source_dir))

# A rooted paper may live beside templates, older drafts, support libraries,
# and standalone supplementary documents.  Filename-only ranking is unsafe:
# it has selected preambles and documentation while silently losing body text.
_ROOT_AUXILIARY_DIRS = frozenset({
    'backup', 'backups', 'old', 'archive', 'archived', 'obsolete',
    'lib', 'libs', 'vendor', 'third_party', 'third-party', 'packages',
    'doc', 'docs', 'documentation', 'examples', 'samples', 'tests',
})
_ROOT_AUXILIARY_NAMES = re.compile(
    r'(?i)(?:^|[_-])(?:preamble|prefix|suffix|macros?|commands?|'
    r'style|styles|packages?|bibliography|bib|definitions?)(?:$|[_-])'
)
_ROOT_HEADING_RE = re.compile(
    r'\\(?:part|chapter|section|subsection|subsubsection|paragraph)\*?'
    r'\s*(?:\[[^\]]*\]\s*)?\{'
)
_ROOT_BEGIN_RE = re.compile(r'\\begin\s*\{document\}')
_ROOT_END_RE = re.compile(r'\\end\s*\{document\}')


def _root_profile_score(source_dir: Path, candidate: Path, *, driver: bool,
                        cached_visible: dict[Path, str]) -> tuple:
    """Rank the source *compilation graph*, not an isolated .tex file.

    This deliberately does not use file size alone: a large TeX package manual
    must not outrank a paper with multiple linked body sections.  The weighted
    signals are evidence, not a proof that the LaTeX compiles.
    """
    relative = candidate.relative_to(source_dir)
    parts = tuple(part.casefold() for part in relative.parts[:-1])
    stem = candidate.stem.casefold()
    aux_dir = any(part in _ROOT_AUXILIARY_DIRS for part in parts)
    aux_name = bool(_ROOT_AUXILIARY_NAMES.search(stem))
    paths = compilation_path(source_dir, root=candidate)
    reachable = [p for p in paths if p.is_file()]
    visible = []
    for source_file in reachable:
        if source_file not in cached_visible:
            cached_visible[source_file] = active_tex(_read_tex(source_file))
        visible.append(cached_visible[source_file])
    headings = sum(len(_ROOT_HEADING_RE.findall(t)) for t in visible)
    body_paths = sum(bool(_ROOT_HEADING_RE.search(t)) for t in visible)
    total_bytes = sum(p.stat().st_size for p in reachable)
    body_related = sum(bool(re.search(r'(?i)(?:intro|method|result|experiment|conclusion|'
                                        r'related.work|discussion|evaluation)', p.stem))
                       for p in reachable)
    has_start = any(_ROOT_BEGIN_RE.search(t) for t in visible)
    has_end = any(_ROOT_END_RE.search(t) for t in visible)
    # \\end{document} in a wrapper that includes the class-bearing preamble
    # is decisive entrypoint evidence, even if the wrapper has no documentclass.
    preferred_name = stem in _PREFERRED_ROOT_NAMES or stem.startswith('main')
    embedded_body = len(reachable) >= 2 and (body_paths > 0 or total_bytes >= 2000)
    score = (
        95 if driver else 0,
        -120 if aux_dir else 0,
        -55 if aux_name else 0,
        32 if has_start and has_end else (10 if has_end else -25),
        20 if preferred_name else 0,
        8 if len(relative.parts) == 1 else 0,
        min(80, max(0, len(reachable) - 1) * 12),
        min(55, headings * 4),
        min(30, body_paths * 6),
        min(18, body_related * 5),
        10 if embedded_body else 0,
        min(15, total_bytes // 16000),
    )
    legacy = _root_score(candidate, source_dir)
    # A template with plausible main.tex name is still not a paper.
    if legacy[2]:
        score += (-115,)
    # The old score is a stable tie-breaker: title agreement, manuscript cues,
    # supplementary labels, depth and lexical order still matter.
    return (-sum(score), legacy)


def find_document_root(source_dir: Path) -> Path | None:
    """Choose a genuine document driver using transitive include evidence.

    In particular, a real ``main.tex`` can include a preamble containing the
    only ``\\documentclass``. Search that caller as well as class-bearing files.
    Comments and verbatim examples never create root candidates.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return None
    source_dir = source_dir.resolve()
    texts: dict[Path, str] = {}
    candidates: list[Path] = []
    for file in sorted(source_dir.rglob('*')):
        if not file.is_file() or file.suffix.lower() != '.tex':
            continue
        p = file.resolve()
        visible = active_tex(_read_tex(p))
        is_class = bool(_DOCUMENTCLASS_RE.search(visible))
        # Keep only potential drivers in memory. Chapter .tex files can be
        # enormous and are reread on demand only if a competing root exists.
        if (is_class or _ROOT_END_RE.search(visible) or
                (p.parent == source_dir and _INCLUDE_ANY_RE.search(visible))):
            texts[p] = visible
        if is_class:
            candidates.append(p)

    if not candidates:
        plain_root = find_plain_tex_root(source_dir)
        if plain_root is not None:
            LOG.info('Plain TeX root detected: %s', plain_root)
        return plain_root

    class_set = set(candidates)
    drivers: set[Path] = set()
    # For files with a real \\end{document}, follow transitive includes to
    # detect a class-bearing preamble (or a nested class declaration). Direct
    # include-only checks missed real M1 driver files.
    for file, visible in texts.items():
        if file in class_set:
            continue
        includes = extract_include_targets(visible)
        if not includes:
            continue
        # The end marker may live in an included paper_suffix.tex. In that
        # case main.tex still is the entrypoint, even without literal \end.
        plausible_wrapper = (_ROOT_END_RE.search(visible) or
                             file.parent == source_dir and
                             (len(includes) >= 2 or file.stem.casefold() in _PREFERRED_ROOT_NAMES))
        if not plausible_wrapper:
            continue
        reachable = compilation_path(source_dir, root=file)
        if not any(p in class_set for p in reachable[1:]):
            continue
        if (_ROOT_END_RE.search(visible) or any(
                _ROOT_END_RE.search(texts.get(p, '')) for p in reachable[1:])):
            drivers.add(file)

    choices = sorted(set(candidates) | drivers)
    if len(choices) == 1:
        return choices[0]

    scored = [( _root_profile_score(source_dir, p, driver=p in drivers,
                                    cached_visible=texts), p) for p in choices]
    scored.sort(key=lambda pair: pair[0])
    chosen = scored[0][1]
    LOG.info(
        'Root selection (%s): chose %s from %d candidates; '
        'top candidates: %s',
        source_dir, chosen.relative_to(source_dir), len(choices),
        [(p.relative_to(source_dir).as_posix(), round(-score[0], 1))
         for score, p in scored[:5]],
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
    search_paths: list[str] = []

    def walk(tex_file: Path) -> None:
        resolved = tex_file.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        ordered.append(resolved)
        text = _read_tex(resolved)
        # Only declarations from reachable files may affect include lookup.
        for entry in extract_input_search_paths(text):
            if entry not in search_paths:
                search_paths.append(entry)
        for target in extract_include_targets(text, flags=flags):
            included = resolve_include_path(source_dir, resolved, target, search_paths)
            if included is not None:
                walk(included)
            elif missing is not None and Path(target).suffix.lower() in {"", ".tex"}:
                missing.append(f"{_relative_source_path(source_dir, resolved)}: {target}")
        # Dynamic commands are opaque to a static resolver. Surface them as
        # partial rather than silently reporting a fully parsed publication.
        if missing is not None:
            visible = active_tex(text)
            for command in re.finditer(
                r"\\(?:input|include|subfile)(?![A-Za-z@])\s*\{\s*\\[A-Za-z@]+",
                visible,
            ):
                snippet = visible[command.start():command.start()+90].split('}', 1)[0] + '}'
                missing.append(f"{_relative_source_path(source_dir, resolved)}: dynamic {snippet}")

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
    return _expand_file(source_dir, root, visited=set(), flags=flags, search_paths=[])


def _expand_file(source_dir: Path, tex_file: Path, visited: set[Path],
                 flags: dict[str, bool], search_paths: list[str],
                 *, as_subfile: bool = False) -> str:
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
        raw = _read_tex(resolved)
        if as_subfile:
            # The subfiles package permits each included chapter to have its
            # own standalone document wrapper. Only its body belongs in main.
            visible = active_tex(raw)
            doc_start = re.search(r"\\begin\s*\{document\}", visible)
            if doc_start:
                doc_end = re.search(r"\\end\s*\{document\}", visible[doc_start.end():])
                stop = doc_start.end() + doc_end.start() if doc_end else len(raw)
                raw = raw[doc_start.end():stop]
        for entry in extract_input_search_paths(raw):
            if entry not in search_paths:
                search_paths.append(entry)
        return f"% FILE: {rel}\n" + _expand_includes(
            active_tex(raw, initial_flags=flags), source_dir, resolved,
            visited, flags, search_paths
        )
    finally:
        visited.remove(resolved)


def _expand_includes(
    text: str,
    source_dir: Path,
    current_file: Path,
    visited: set[Path],
    flags: dict[str, bool],
    search_paths: list[str],
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
            match = _INCLUDE_ANY_RE.match(text, i)
            if match:
                target = _include_target(match).strip().strip("'\"")
                if not target or target.startswith(("\\", "#")) or "#" in target:
                    out.append(text[i:match.end()])
                    i = match.end()
                    continue
                included = resolve_include_path(source_dir, current_file, target, search_paths)
                if included is not None:
                    out.append(_expand_file(source_dir, included, visited, flags, search_paths,
                                            as_subfile=(match.group(3) is not None)))
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
    for tex_file in sorted(source_dir.rglob("*")):
        if tex_file.is_file() and tex_file.suffix.lower() == ".tex" and tex_file.resolve() not in used:
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
    is_subfiles_class = bool(re.search(
        r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{\s*subfiles\s*\}", tex))
    is_supp = bool(re.search(r"supp(?:lement(?:ary|al)?)?|appendix|(^|[_-])si($|[_-])", name, re.I))
    is_supp |= bool(re.match(r"\s*(?:supplement(?:ary|al)?|appendix)\b", _title_words(title)))
    has_begin = bool(re.search(r"\\begin\s*\{document\}", tex))
    # A class declaration inside an author/template HOWTO is not evidence that
    # the file is the paper. Check for distinctive instructional prose rather
    # than just a broad occurrence of 'template' (which may be a paper topic).
    guide_name = bool(re.search(r"(?:^|[_-])(?:template|sample|example|guide|instructions?|readme|howto)(?:$|[_-])", name))
    guide_text = bool(re.search(
        r"(?i)(?:replace (?:this|these|all|with your)|"
        r"(?:author|submission|formatting) (?:instructions?|guidelines)|"
        r"(?:how to (?:use|prepare|submit) (?:this|your)|"
        r"this (?:template|sample (?:file|document)) is)|"
        r"(?:dummy|placeholder) (?:text|title|abstract)|"
        r"\\section\*?\s*\{\s*(?:instructions?|template|sample)\s*\})",
        tex[:15000],
    ))
    is_guide = guide_name or guide_text
    section_count = len(re.findall(r"\\(?:section|chapter)\*?\s*(?:\[[^]]*\])?\s*\{", tex))
    has_abstract = bool(re.search(r"\\begin\s*\{abstract\}|\\abstract\b", tex))
    has_maketitle = bool(re.search(r"\\maketitle\b", tex))
    # Manuscript evidence precedes a filename heuristic. Cap section count so
    # a long template cannot beat a genuine main driver on length alone.
    manuscript_signals = (2 * bool(title) + 2 * has_abstract +
                          int(has_maketitle) + min(section_count, 3) +
                          int(bool(_INCLUDE_ANY_RE.search(tex))))
    return (
        -round(title_score, 4) if paper_title and title else 0,
        int(is_supp),
        int(is_guide),
        int(is_subfiles_class),
        -manuscript_signals,
        0 if name in _PREFERRED_ROOT_NAMES or name.startswith('main') else 1,
        0 if has_begin else 1,
        len(rel.parts),
        rel.as_posix(),
    )