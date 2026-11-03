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

import re
from dataclasses import dataclass, field

from src.common.schemas import ELEMENT_KINDS

_HEADING_LEVELS = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "subparagraph": 7,
}

_HEADING_COMMANDS = frozenset(_HEADING_LEVELS)

_BLOCK_MATH_ENVS = frozenset(
    {
        "equation",
        "equation*",
        "align",
        "align*",
        "aligned",
        "gather",
        "gather*",
        "flalign",
        "flalign*",
        "multline",
        "multline*",
        "displaymath",
        "eqnarray",
        "eqnarray*",
        "alignat",
        "alignat*",
        "mathdisplay",
    }
)

_FIGURE_ENVS = frozenset(
    {
        "figure",
        "figure*",
        "wrapfigure",
        "sidewaysfigure",
        "subfigure",
    }
)

_TABLE_ENVS = frozenset(
    {
        "table",
        "table*",
        "wraptable",
        "sidewaystable",
        "tabular",
        "tabular*",
        "tabularx",
        "longtable",
        "longtable*",
    }
)

_LIST_ENVS = frozenset({"itemize", "enumerate", "description"})

_SKIP_ENVS = frozenset(
    {
        "thebibliography",
        "bibliography",
        "filecontents",
        "filecontents*",
        "comment",
    }
)

_VERBATIM_ENVS = frozenset(
    {
        "verbatim",
        "verbatim*",
        "lstlisting",
        "minted",
        "alltt",
        "spverbatim",
        "Verbatim",
        "lstlisting*",
    }
)

_STRUCTURAL_ENVS = frozenset(
    {
        "abstract",
        "quote",
        "quotation",
        "proof",
        "theorem",
        "lemma",
        "proposition",
        "corollary",
        "definition",
        "remark",
        "example",
        "minipage",
        "center",
        "flushleft",
        "flushright",
        "titlepage",
        "keywords",
        "IEEEkeywords",
        "highlights",
    }
)

_SKIP_COMMANDS = frozenset(
    {
        "maketitle",
        "tableofcontents",
        "listoffigures",
        "listoftables",
        "newpage",
        "clearpage",
        "cleardoublepage",
        "noindent",
        "indent",
        "centering",
        "bibliography",
        "bibliographystyle",
        "documentclass",
        "usepackage",
        "RequirePackage",
        "hypersetup",
        "geometry",
        "graphicspath",
        "addcontentsline",
        "thispagestyle",
        "pagestyle",
        "pagenumbering",
        "onecolumn",
        "twocolumn",
        "newpage",
        "linebreak",
        "nolinebreak",
        "pagebreak",
        "nopagebreak",
    }
)

_ABBREVIATIONS = frozenset(
    {
        "i.e",
        "e.g",
        "etc",
        "vs",
        "cf",
        "al",
        "fig",
        "figs",
        "eq",
        "eqs",
        "tab",
        "tbl",
        "sec",
        "secs",
        "ref",
        "refs",
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "vol",
        "no",
        "nos",
        "pp",
        "ca",
        "viz",
        "inc",
        "ltd",
        "jr",
        "sr",
        "approx",
        "dept",
        "univ",
        "ed",
        "eds",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "st",
        "nd",
        "rd",
        "th",
        "u.s",
        "u.k",
        "n.y",
        "ph.d",
        "a.k.a",
        "w.r.t",
    }
)

_REF_TITLES = frozenset(
    {
        "references",
        "reference",
        "bibliography",
        "bibliographie",
        "works cited",
        "literature cited",
        "cited literature",
        "bibliographical references",
        "references and notes",
        "literature",
    }
)

_ACK_RE = re.compile(r"acknowledge?ments?|thanks", re.I)
_APP_RE = re.compile(r"^appendix(es)?\b|^supplementary\b", re.I)
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z@]+\*?")
_BRACE_RE = re.compile(r"[{}$]")


@dataclass
class ParseNode:
    """Node tạm trong cây 1 version (trước khi gán element_id / dedup)."""

    kind: str
    content: str
    children: list["ParseNode"] = field(default_factory=list)
    source_hint: str = ""  # ví dụ 'section:Introduction'

    def to_dict(self) -> dict:
        if self.kind not in ELEMENT_KINDS:
            # Keep unknown kinds visible rather than silently dropping.
            pass
        return {
            "kind": self.kind,
            "content": self.content,
            "source_hint": self.source_hint,
            "children": [child.to_dict() for child in self.children],
        }


def heading_level(command: str) -> int | None:
    """
    Map lệnh heading → độ sâu. None nếu không phải heading.

    Cần code bên trong (gợi ý):
    - part=1, chapter=2, section=3, subsection=4, subsubsection=5, paragraph=6, subparagraph=7
    - starred forms (\\section*) cùng level.
    """
    name = command.strip().lstrip("\\").rstrip("*").lower()
    return _HEADING_LEVELS.get(name)


def is_references_heading(title: str) -> bool:
    """True nếu section là bibliography/references → skip cả subtree."""
    plain = _plain_title(title)
    if not plain:
        return False
    if plain in _REF_TITLES:
        return True
    if plain.startswith("references ") or plain.startswith("bibliography "):
        return True
    return False


def is_acknowledgement_or_appendix(title: str, command: str) -> str | None:
    """
    Trả 'acknowledgement' / 'appendix' / None.

    Cần code bên trong: match appendix, acknowledgement(s); \\appendix switch của LaTeX.
    """
    name = command.strip().lstrip("\\").rstrip("*").lower()
    if name == "appendix":
        return "appendix"
    plain = _plain_title(title)
    if not plain:
        return None
    if _ACK_RE.search(plain) and len(plain) < 80:
        return "acknowledgement"
    if _APP_RE.search(plain):
        return "appendix"
    return None


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
    if not prose or not prose.strip():
        return []

    text = prose.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    n = len(text)
    bounds: list[int] = []
    i = 0
    math_dollar = False
    math_paren = False
    brace_depth = 0

    while i < n:
        ch = text[i]

        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "(":
                math_paren = True
                i += 2
                continue
            if nxt == ")" and math_paren:
                math_paren = False
                i += 2
                continue
            if nxt in "%$&_#{}" or nxt == "\\":
                i += 2
                continue
            # command name + optional * [args] {args}
            i = _skip_command(text, i)
            continue

        if math_dollar or math_paren:
            if ch == "$" and not math_paren:
                math_dollar = False
            i += 1
            continue

        if ch == "$":
            math_dollar = True
            i += 1
            continue

        if ch == "{":
            brace_depth += 1
            i += 1
            continue
        if ch == "}" and brace_depth:
            brace_depth -= 1
            i += 1
            continue

        if brace_depth == 0 and ch in ".?!":
            if _is_sentence_boundary(text, i):
                bounds.append(i + 1)
        i += 1

    sentences: list[str] = []
    start = 0
    for end in bounds + [n]:
        chunk = text[start:end].strip()
        if chunk:
            sentences.append(chunk)
        start = end
    return sentences


def parse_tex_to_tree(tex: str) -> ParseNode:
    """
    Parser chính: tex đã concat + (nên) đã cleanup/normalize math.

    Cần code bên trong:
    - Root kind='document'
    - Walk token/environment: heading, itemize, equation, figure, table, thebibliography (skip)
    - Prose → paragraph → sentence leaves
    - Empty tex → root rỗng (version empty, vẫn record)
    """
    title = _extract_title(tex) if tex else ""
    root = ParseNode(kind="document", content=title, source_hint="document")
    if not tex or not tex.strip():
        return root
    body, start = _document_body(tex)
    parser = _HierarchyParser(body, root)
    parser.parse()
    return root


def flatten_tree(root: ParseNode) -> list[tuple[ParseNode, ParseNode | None]]:
    """Duyệt preorder → (node, parent|None)."""
    out: list[tuple[ParseNode, ParseNode | None]] = []

    def walk(node: ParseNode, parent: ParseNode | None) -> None:
        out.append((node, parent))
        for child in node.children:
            walk(child, node)

    walk(root, None)
    return out


def nodes_and_edges(
    root: ParseNode, *, version: int
) -> tuple[list[dict], list[dict]]:
    """
    Cây 1 version → nodes + cạnh cha–con, ID local (trước dedup/chuẩn hóa).

    local id: v{version}#n{preorder_index}
    Root không có cạnh parent (khớp schema hierarchy: chỉ emit cạnh con→cha).
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    def walk(node: ParseNode, parent_id: str | None) -> str:
        local_id = f"v{version}#n{len(nodes)}"
        nodes.append(
            {
                "local_id": local_id,
                "kind": node.kind,
                "content": node.content,
                "source_hint": node.source_hint,
            }
        )
        if parent_id is not None:
            edges.append(
                {
                    "parent_id": parent_id,
                    "child_id": local_id,
                    "version": version,
                }
            )
        for child in node.children:
            walk(child, local_id)
        return local_id

    walk(root, None)
    return nodes, edges


def _plain_title(title: str) -> str:
    text = _LATEX_CMD_RE.sub(" ", title)
    text = _BRACE_RE.sub(" ", text)
    text = re.sub(r"[^A-Za-z0-9\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_title(tex: str) -> str:
    match = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", tex)
    if not match:
        return ""
    content, _ = _read_braced(tex, match.end() - 1)
    return re.sub(r"\s+", " ", content).strip()


def _document_body(tex: str) -> tuple[str, int]:
    begin = re.search(r"\\begin\s*\{document\}", tex)
    if not begin:
        return tex, 0
    end = re.search(r"\\end\s*\{document\}", tex)
    if end and end.start() > begin.end():
        return tex[begin.end() : end.start()], begin.end()
    return tex[begin.end() :], begin.end()


def _is_sentence_boundary(text: str, index: int) -> bool:
    ch = text[index]
    n = len(text)
    if ch == "." and index + 1 < n and text[index + 1] == ".":
        return False
    nxt = _next_nonspace(text, index + 1)
    if nxt is None:
        return True

    if ch == ".":
        prev = text[index - 1] if index else ""
        if prev.isdigit() and text[nxt].isdigit():
            return False
        if prev.isalpha() and text[nxt].isalpha() and nxt == index + 1:
            # e.g. file.tex or i.e. without space after inner dots
            return False
        if _looks_like_url_dot(text, index):
            return False
        if _looks_like_abbreviation(text, index):
            return False
        after = text[index + 1 : nxt] if nxt > index + 1 else ""
        if after.strip() == "" and text[nxt].islower():
            return False
        if after.strip() == "" and text[nxt].isdigit():
            # Fig. 1 / Eq. 2
            word = _token_before_period(text, index).lower().rstrip(".")
            if word in {"fig", "figs", "eq", "eqs", "tab", "sec", "ref", "refs", "vol", "no", "pp"}:
                return False
    rest = text[index + 1 :]
    if rest.strip() == "":
        return True
    return bool(re.match(r"\s", text[index + 1 : index + 2] or " "))


def _next_nonspace(text: str, start: int) -> int | None:
    i = start
    while i < len(text):
        if not text[i].isspace():
            return i
        i += 1
    return None


def _token_before_period(text: str, index: int) -> str:
    j = index - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    end = j + 1
    while j >= 0 and (text[j].isalnum() or text[j] in ".-"):
        j -= 1
    return text[j + 1 : end]


def _looks_like_abbreviation(text: str, index: int) -> bool:
    token = _token_before_period(text, index).lower().rstrip(".")
    if token in _ABBREVIATIONS:
        return True
    # et al.
    if token == "al":
        before = text[: index - len("al")].rstrip()
        if before.lower().endswith("et"):
            return True
    # U.S.A. style: single capital letter
    raw = _token_before_period(text, index)
    if len(raw.rstrip(".")) == 1 and raw[0].isupper():
        return True
    return False


def _looks_like_url_dot(text: str, index: int) -> bool:
    """True only for dots *inside* a URL/email, not the period that ends the sentence."""
    start = max(0, index - 64)
    window = text[start:index]
    in_url = bool(re.search(r"(?:https?://|ftp://|www\.)\S*$", window, re.I))
    in_email = bool(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]*$", window))
    if not in_url and not in_email:
        return False
    nxt = index + 1
    if nxt >= len(text):
        return False
    # A URL/email continues without whitespace; a sentence period is followed by space.
    return text[nxt] not in " \t\n\r)]}\"'"


def _skip_command(text: str, i: int) -> int:
    n = len(text)
    i += 1
    if i < n and text[i] in " ,;:'`\"[]()":
        return i + 1
    while i < n and (text[i].isalpha() or text[i] == "@"):
        i += 1
    if i < n and text[i] == "*":
        i += 1
    while True:
        while i < n and text[i] in " \t":
            i += 1
        if i < n and text[i] == "[":
            depth = 1
            i += 1
            while i < n and depth:
                if text[i] == "[" and not _escaped(text, i):
                    depth += 1
                elif text[i] == "]" and not _escaped(text, i):
                    depth -= 1
                i += 1
            continue
        if i < n and text[i] == "{":
            _, i = _read_braced(text, i)
            continue
        break
    return i


def _escaped(text: str, index: int) -> bool:
    slashes = 0
    j = index - 1
    while j >= 0 and text[j] == "\\":
        slashes += 1
        j -= 1
    return slashes % 2 == 1


def _read_braced(text: str, i: int) -> tuple[str, int]:
    """i points at '{'. Returns inner content and index after closing '}'."""
    n = len(text)
    if i >= n or text[i] != "{":
        return "", i
    depth = 0
    start = i + 1
    i += 1
    while i < n:
        ch = text[i]
        if ch == "{" and not _escaped(text, i):
            depth += 1
        elif ch == "}" and not _escaped(text, i):
            if depth == 0:
                return text[start:i], i + 1
            depth -= 1
        i += 1
    return text[start:], n


def _read_bracketed(text: str, i: int) -> tuple[str, int]:
    n = len(text)
    if i >= n or text[i] != "[":
        return "", i
    depth = 0
    start = i + 1
    i += 1
    while i < n:
        ch = text[i]
        if ch == "[" and not _escaped(text, i):
            depth += 1
        elif ch == "]" and not _escaped(text, i):
            if depth == 0:
                return text[start:i], i + 1
            depth -= 1
        i += 1
    return text[start:], n


class _HierarchyParser:
    def __init__(self, tex: str, root: ParseNode) -> None:
        self.tex = tex
        self.n = len(tex)
        self.i = 0
        self.root = root
        self.stack: list[tuple[int, ParseNode]] = [(0, root)]
        self.in_appendix = False
        self.skip_until_level: int | None = None
        self.prose: list[str] = []

    def parse(self) -> None:
        while self.i < self.n:
            self._step()
        self._flush_prose()

    def _step(self) -> None:
        ch = self.tex[self.i]
        if ch == "%" and not _escaped(self.tex, self.i):
            self._flush_prose()
            while self.i < self.n and self.tex[self.i] != "\n":
                self.i += 1
            return
        if self.tex.startswith("$$", self.i):
            self._flush_prose()
            self._take_display_dollar()
            return
        if ch == "\\" and self.i + 1 < self.n:
            nxt = self.tex[self.i + 1]
            if nxt == "[":
                self._flush_prose()
                self._take_display_bracket()
                return
            if nxt.isalpha() or nxt == "@":
                self._handle_command()
                return
            self.prose.append(ch)
            self.i += 1
            return
        self.prose.append(ch)
        self.i += 1

    def _handle_command(self) -> None:
        cmd, after_name = self._read_command_name(self.i)
        if cmd == "begin":
            self._flush_prose()
            self.i = after_name
            env, self.i = self._optional_braced_name()
            self._handle_begin(env)
            return
        if cmd == "end":
            self._flush_prose()
            self.i = after_name
            _env, self.i = self._optional_braced_name()
            return
        if cmd == "appendix":
            self._flush_prose()
            self.in_appendix = True
            self.i = after_name
            return
        if cmd in _HEADING_COMMANDS:
            self._flush_prose()
            self._handle_heading(cmd, after_name)
            return
        if cmd in _SKIP_COMMANDS:
            self._flush_prose()
            self.i = _skip_command(self.tex, self.i)
            return
        if cmd in {"item"}:
            # stray \item outside list: treat as list of one
            self._flush_prose()
            self.i = after_name
            self._skip_optional_star_and_bracket()
            return
        # Keep ordinary commands in the prose stream (citations, inline math, etc.)
        end = _skip_command(self.tex, self.i)
        self.prose.append(self.tex[self.i : end])
        self.i = end

    def _handle_heading(self, cmd: str, after_name: int) -> None:
        self.i = after_name
        if self.i < self.n and self.tex[self.i] == "*":
            self.i += 1
        self._skip_ws()
        if self.i < self.n and self.tex[self.i] == "[":
            _, self.i = _read_bracketed(self.tex, self.i)
            self._skip_ws()
        title = ""
        if self.i < self.n and self.tex[self.i] == "{":
            title, self.i = _read_braced(self.tex, self.i)
        title = re.sub(r"\s+", " ", title).strip()
        level = heading_level(cmd) or 3

        if self.skip_until_level is not None:
            if level <= self.skip_until_level:
                self.skip_until_level = None
            else:
                return

        if is_references_heading(title):
            self.skip_until_level = level
            return

        while len(self.stack) > 1 and self.stack[-1][0] >= level:
            self.stack.pop()

        special = is_acknowledgement_or_appendix(title, cmd)
        kind = "heading"
        if self.in_appendix:
            kind = "appendix"
        if special:
            kind = special
        node = ParseNode(
            kind=kind,
            content=title,
            source_hint=f"{cmd}:{title}",
        )
        self.stack[-1][1].children.append(node)
        self.stack.append((level, node))

    def _handle_begin(self, env: str) -> None:
        env_norm = env.strip()
        if self.skip_until_level is not None:
            self._skip_environment(env_norm)
            return
        if env_norm in _SKIP_ENVS:
            self._skip_environment(env_norm)
            return
        if env_norm in _VERBATIM_ENVS:
            body = self._consume_environment_body(env_norm)
            self._add_leaf("sentence", body.strip(), hint=f"verbatim:{env_norm}")
            return
        if env_norm in _BLOCK_MATH_ENVS:
            body = self._consume_environment_body(env_norm)
            content = f"\\begin{{{env_norm}}}{body}\\end{{{env_norm}}}"
            self._add_leaf("formula", content.strip(), hint=f"math:{env_norm}")
            return
        if env_norm in _FIGURE_ENVS or env_norm in _TABLE_ENVS:
            body = self._consume_environment_body(env_norm)
            content = f"\\begin{{{env_norm}}}{body}\\end{{{env_norm}}}"
            self._add_leaf("figure", content.strip(), hint=f"float:{env_norm}")
            return
        if env_norm in _LIST_ENVS:
            body = self._consume_environment_body(env_norm)
            list_node = ParseNode(kind="list", content=env_norm, source_hint=f"list:{env_norm}")
            self._current().children.append(list_node)
            self._parse_list_body(body, list_node)
            return
        if env_norm == "abstract":
            body = self._consume_environment_body(env_norm)
            node = ParseNode(kind="heading", content="Abstract", source_hint="env:abstract")
            self.root.children.insert(0, node)
            inner = _HierarchyParser(body, node)
            inner.stack = [(3, node)]
            inner.parse()
            return
        # Generic container: parse inner TeX into the current parent.
        body = self._consume_environment_body(env_norm)
        inner = _HierarchyParser(body, self._current())
        inner.stack = list(self.stack)
        inner.in_appendix = self.in_appendix
        inner.parse()

    def _parse_list_body(self, body: str, list_node: ParseNode) -> None:
        items = _split_list_items(body)
        for raw_item in items:
            item_node = ParseNode(kind="list_item", content="", source_hint="item")
            list_node.children.append(item_node)
            inner = _HierarchyParser(raw_item, item_node)
            inner.stack = [(99, item_node)]
            inner.in_appendix = self.in_appendix
            inner.parse()

    def _take_display_dollar(self) -> None:
        if self.skip_until_level is not None:
            self.i += 2
            end = self.tex.find("$$", self.i)
            self.i = self.n if end < 0 else end + 2
            return
        start = self.i
        self.i += 2
        end = self.tex.find("$$", self.i)
        if end < 0:
            body = self.tex[start:]
            self.i = self.n
        else:
            body = self.tex[start : end + 2]
            self.i = end + 2
        self._add_leaf("formula", body.strip(), hint="math:$$")

    def _take_display_bracket(self) -> None:
        if self.skip_until_level is not None:
            self.i += 2
            end = self.tex.find("\\]", self.i)
            self.i = self.n if end < 0 else end + 2
            return
        start = self.i
        self.i += 2
        end = self.tex.find("\\]", self.i)
        if end < 0:
            body = self.tex[start:]
            self.i = self.n
        else:
            body = self.tex[start : end + 2]
            self.i = end + 2
        self._add_leaf("formula", body.strip(), hint="math:[")

    def _add_leaf(self, kind: str, content: str, hint: str = "") -> None:
        if not content:
            return
        self._current().children.append(
            ParseNode(kind=kind, content=content, source_hint=hint)
        )

    def _flush_prose(self) -> None:
        raw = "".join(self.prose)
        self.prose = []
        if self.skip_until_level is not None:
            return
        raw = raw.replace("\r\n", "\n")
        if not raw.strip():
            return
        for para in re.split(r"\n\s*\n", raw):
            para = para.strip()
            if not para:
                continue
            sentences = split_sentences(para)
            if not sentences:
                continue
            pnode = ParseNode(kind="paragraph", content="", source_hint="paragraph")
            for sentence in sentences:
                pnode.children.append(
                    ParseNode(kind="sentence", content=sentence, source_hint="sentence")
                )
            self._current().children.append(pnode)

    def _current(self) -> ParseNode:
        return self.stack[-1][1]

    def _read_command_name(self, i: int) -> tuple[str, int]:
        assert self.tex[i] == "\\"
        i += 1
        start = i
        n = self.n
        while i < n and (self.tex[i].isalpha() or self.tex[i] == "@"):
            i += 1
        return self.tex[start:i], i

    def _optional_braced_name(self) -> tuple[str, int]:
        self._skip_ws()
        if self.i < self.n and self.tex[self.i] == "{":
            name, nxt = _read_braced(self.tex, self.i)
            return name.strip(), nxt
        return "", self.i

    def _skip_optional_star_and_bracket(self) -> None:
        if self.i < self.n and self.tex[self.i] == "*":
            self.i += 1
        self._skip_ws()
        if self.i < self.n and self.tex[self.i] == "[":
            _, self.i = _read_bracketed(self.tex, self.i)

    def _skip_ws(self) -> None:
        while self.i < self.n and self.tex[self.i] in " \t":
            self.i += 1

    def _consume_environment_body(self, env: str) -> str:
        start = self.i
        self._skip_environment(env)
        end_token = f"\\end{{{env}}}"
        # self.i is after \end{env}; body is before that token
        end_at = self.tex.rfind(end_token, start, self.i)
        if end_at < 0:
            return self.tex[start : self.i]
        return self.tex[start:end_at]

    def _skip_environment(self, env: str) -> None:
        depth = 1
        begin = f"\\begin{{{env}}}"
        end = f"\\end{{{env}}}"
        while self.i < self.n and depth:
            if self.tex[self.i] == "%" and not _escaped(self.tex, self.i):
                while self.i < self.n and self.tex[self.i] != "\n":
                    self.i += 1
                continue
            if self.tex.startswith(begin, self.i):
                depth += 1
                self.i += len(begin)
                continue
            if self.tex.startswith(end, self.i):
                depth -= 1
                self.i += len(end)
                continue
            self.i += 1


def _split_list_items(body: str) -> list[str]:
    """Split a list environment body on top-level \\item commands."""
    items: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(body)
    depth = 0
    while i < n:
        if body[i] == "%" and not _escaped(body, i):
            while i < n and body[i] != "\n":
                i += 1
            continue
        if body.startswith("\\begin{", i):
            name_start = i + len("\\begin{")
            name_end = body.find("}", name_start)
            if name_end > 0:
                depth += 1
                buf.append(body[i : name_end + 1])
                i = name_end + 1
                continue
        if body.startswith("\\end{", i) and depth:
            name_start = i + len("\\end{")
            name_end = body.find("}", name_start)
            if name_end > 0:
                depth -= 1
                buf.append(body[i : name_end + 1])
                i = name_end + 1
                continue
        if depth == 0 and body.startswith("\\item", i) and (
            i + 5 == n or not body[i + 5].isalpha()
        ):
            if buf and any(part.strip() for part in buf):
                items.append("".join(buf).strip())
            buf = []
            i += 5
            # drop optional [label]
            while i < n and body[i] in " \t":
                i += 1
            if i < n and body[i] == "[":
                _, i = _read_bracketed(body, i)
            continue
        buf.append(body[i])
        i += 1
    if buf and any(part.strip() for part in buf):
        items.append("".join(buf).strip())
    return items
