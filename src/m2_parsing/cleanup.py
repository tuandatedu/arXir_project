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
    """Normalize single display blocks; preserve multi-line align/gather semantics."""
    tex = re.sub(r"\$\$(.*?)\$\$", lambda m: _equation(m[1]), tex, flags=re.S)
    tex = re.sub(r"\\\[(.*?)\\\]", lambda m: _equation(m[1]), tex, flags=re.S)
    for env in ("equation*", "displaymath", "mathdisplay"):
        tex = re.sub(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}",
                     lambda m: _equation(m[1]), tex, flags=re.S)
    return tex


def _equation(body: str) -> str:
    return "\\begin{equation}" + body.strip() + "\\end{equation}"


def cleanup_element_content(content: str) -> str:
    """Return a stable, semantically equivalent string for an element."""
    return remove_non_semantic_commands(normalize_block_math(normalize_inline_math(content)))


def cleanup_document(tex: str) -> str:
    """Normalize TeX before parsing when a caller explicitly needs that form."""
    return remove_non_semantic_commands(normalize_block_math(normalize_inline_math(tex)))
