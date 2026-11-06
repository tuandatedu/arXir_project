"""Conservative LaTeX cleanup applied to parsed elements before deduplication."""

from __future__ import annotations

import re


_SPACING = re.compile(r"\\(?:centering|raggedright|raggedleft|hfill|vfill|newpage|clearpage|pagebreak|noindent|smallskip|medskip|bigskip|hline|toprule|midrule|bottomrule|maketitle|tableofcontents)\b(?:\[\d+\])?")
_SPACE_ARGS = re.compile(r"\\(?:vspace|hspace|vskip|hskip)\*?\s*\{[^{}]*\}")
_FLOAT_PLACEMENT = re.compile(r"(\\begin\{(?:figure|figure\*|table|table\*|subfigure)\})\s*\[(?:[!htbpH]+)\]")
_TEXT_STYLE = re.compile(r"\\(?:textbf|textit|textsc|textsf|textrm|texttt|textnormal|emph|underline|mbox)\s*\{([^{}]*)\}")
_FONT_SWITCH = re.compile(r"\\(?:bfseries|itshape|slshape|scshape|rmfamily|sffamily|ttfamily|small|footnotesize|scriptsize|tiny|normalsize|large|Large|LARGE|huge|Huge)\b")


def remove_non_semantic_commands(tex: str) -> str:
    """Remove presentation-only tokens without deleting figures or semantic commands."""
    tex = _FLOAT_PLACEMENT.sub(r"\1", tex)
    while True:
        unwrapped = _TEXT_STYLE.sub(r"\1", tex)
        if unwrapped == tex:
            break
        tex = unwrapped
    tex = _SPACE_ARGS.sub(" ", tex)
    tex = _SPACING.sub(" ", tex)
    tex = _FONT_SWITCH.sub(" ", tex)
    return re.sub(r"\s+", " ", tex).strip()


def normalize_inline_math(tex: str) -> str:
    """Use dollar delimiters for inline math, preserving the math body."""
    tex = re.sub(r"\\\((.*?)\\\)", lambda m: f"${m[1].strip()}$", tex, flags=re.S)
    tex = re.sub(r"\\begin\{math\}(.*?)\\end\{math\}", lambda m: f"${m[1].strip()}$", tex, flags=re.S)
    return re.sub(r"\\ensuremath\{([^{}]*)\}", lambda m: f"${m[1].strip()}$", tex)


def normalize_block_math(tex: str) -> str:
    """Canonicalize display delimiters, preserving alignment and star status."""
    tex = re.sub(r"\$\$(.*?)\$\$", lambda m: _equation(m[1], starred=True), tex, flags=re.S)
    tex = re.sub(r"\\\[(.*?)\\\]", lambda m: _equation(m[1], starred=True), tex, flags=re.S)
    for env in ("displaymath", "mathdisplay"):
        tex = re.sub(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}",
                     lambda m: _equation(m[1], starred=True), tex, flags=re.S)
    for env, inner in (("align", "aligned"), ("gather", "gathered")):
        for star in ("", "*"):
            name = env + star
            pattern = r"\\begin\{" + re.escape(name) + r"\}(.*?)\\end\{" + re.escape(name) + r"\}"
            def convert(match: re.Match[str], i: str = inner, s: str = star) -> str:
                body = match[1].strip()
                # Numbered multi-row displays have per-row labels/numbers;
                # equation+aligned would silently change those semantics.
                if not s and (r"\\" in body or re.search(r"\\(?:label|tag|notag|nonumber)\b", body)):
                    return match[0]
                return ("\\begin{equation" + s + "}\\begin{" + i + "}" + body
                        + "\\end{" + i + "}\\end{equation" + s + "}")
            tex = re.sub(pattern, convert, tex, flags=re.S)
    return tex


def _equation(body: str, starred: bool = False) -> str:
    env = "equation*" if starred else "equation"
    return "\\begin{" + env + "}" + body.strip() + "\\end{" + env + "}"


def cleanup_element_content(content: str) -> str:
    """Return a stable, semantically equivalent string for an element."""
    return remove_non_semantic_commands(normalize_block_math(normalize_inline_math(content)))


def cleanup_document(tex: str) -> str:
    """Normalize TeX before parsing when a caller explicitly needs that form."""
    return remove_non_semantic_commands(normalize_block_math(normalize_inline_math(tex)))
