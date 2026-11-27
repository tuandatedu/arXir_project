"""Context-aware cleanup preserves math text boxes and font semantics."""
from __future__ import annotations
import re
from functools import lru_cache
from .tex_spans import spans

_SPACING = re.compile(r"\\(?:centering|raggedright|raggedleft|hfill|vfill|newpage|clearpage|pagebreak|noindent|smallskip|medskip|bigskip|hline|toprule|midrule|bottomrule|maketitle|tableofcontents)\b(?:\[\d+\])?")
_SPACE_ARGS = re.compile(r"\\(?:vspace|hspace|vskip|hskip)\*?\s*\{[^{}]*\}")
_FLOAT_PLACEMENT = re.compile(r"(\\begin\{(?:figure|figure\*|table|table\*|subfigure)\})\s*\[(?:[!htbpH]+)\]")
_TEXT_STYLE = re.compile(r"\\(?:textbf|textit|textsc|textsf|textrm|texttt|textnormal|emph|underline)\s*\{([^{}]*)\}")
_FONT_SWITCH = re.compile(r"\\(?:bfseries|itshape|slshape|scshape|rmfamily|sffamily|ttfamily|small|footnotesize|scriptsize|tiny|normalsize|large|Large|LARGE|huge|Huge)\b")

def remove_non_semantic_commands(tex: str) -> str:
    def prose(part):
        part = _FLOAT_PLACEMENT.sub(r'\1', part)
        while True:
            new = _TEXT_STYLE.sub(r'\1', part)
            if new == part: break
            part = new
        part = _SPACE_ARGS.sub(' ', part)
        part = _SPACING.sub(' ', part)
        return re.sub(r'\s+', ' ', _FONT_SWITCH.sub(' ', part))
    return ''.join(prose(raw) if kind == 'text' else raw
                   for kind, raw, _, _ in spans(tex)).strip()

def normalize_inline_math(tex: str) -> str:
    return ''.join('$' + body.strip() + '$'
                   if kind == 'math' and delim in (r'\(', 'math', 'ensuremath')
                   else raw for kind, raw, body, delim in spans(tex))

def _equation(body: str, starred: bool = False) -> str:
    env = 'equation*' if starred else 'equation'
    return '\\begin{' + env + '}' + body.strip() + '\\end{' + env + '}'

def normalize_block_math(tex: str) -> str:
    parts = []
    for kind, raw, body, delim in spans(tex):
        if kind == 'math' and delim in ('$$', r'\[', 'displaymath', 'mathdisplay'):
            raw = _equation(body, starred=True)
        elif kind == 'math' and delim.rstrip('*') in ('align', 'gather'):
            star = '*' if delim.endswith('*') else ''
            if star or not (r'\\' in body or re.search(r'\\(?:label|tag|notag|nonumber)\b', body)):
                inner = 'aligned' if delim.startswith('align') else 'gathered'
                raw = _equation('\\begin{' + inner + '}' + body.strip() + '\\end{' + inner + '}', bool(star))
        parts.append(raw)
    return ''.join(parts)

@lru_cache(maxsize=32768)
def cleanup_element_content(content: str) -> str:
    return remove_non_semantic_commands(normalize_block_math(normalize_inline_math(content)))

def cleanup_document(tex: str) -> str:
    return cleanup_element_content(tex)
