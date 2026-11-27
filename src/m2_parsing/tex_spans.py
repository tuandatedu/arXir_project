"""Lexical spans keep math and literal TeX out of prose rewrites."""
from __future__ import annotations
import re

MATH_ENVS = {'math', 'displaymath', 'mathdisplay', 'equation', 'align',
             'gather', 'multline', 'flalign', 'alignat', 'eqnarray',
             'aligned', 'gathered', 'split', 'cases', 'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Bmatrix', 'Vmatrix'}
LITERAL_ENVS = {'verbatim', 'Verbatim', 'lstlisting', 'minted', 'alltt'}

def escaped(text: str, pos: int) -> bool:
    n = 0
    while pos > 0 and text[pos - 1] == '\\':
        n += 1
        pos -= 1
    return bool(n % 2)

def group(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text) or text[pos] != '{': return None
    depth = 1
    for i in range(pos + 1, len(text)):
        if escaped(text, i): continue
        if text[i] == '{': depth += 1
        if text[i] == '}': depth -= 1
        if depth == 0: return text[pos + 1:i], i + 1
    return None

def spans(text: str):
    """Yield (kind, raw, body, delimiter); leave malformed spans untouched."""
    i = start = 0
    while i < len(text):
        end = None
        kind = 'math'
        body = delim = ''
        if text[i] == '\\' and not escaped(text, i):
            env = re.match(r'\\begin\{([^{}]+)\}', text[i:])
            verb = re.match(r'\\verb\*?([^A-Za-z\s])', text[i:])
            ensure = re.match(r'\\ensuremath\s*', text[i:])
            if env and env[1].rstrip('*') in MATH_ENVS | LITERAL_ENVS:
                delim = env[1]
                close = '\\end{' + delim + '}'
                j = text.find(close, i + env.end())
                if j >= 0:
                    end = j + len(close)
                    body = text[i + env.end():j]
                    kind = 'literal' if delim.rstrip('*') in LITERAL_ENVS else 'math'
            elif verb:
                j = text.find(verb[1], i + verb.end())
                if j >= 0: end, kind = j + 1, 'literal'
            elif ensure:
                found = group(text, i + ensure.end())
                if found:
                    body, end = found
                    delim = 'ensuremath'
            elif text[i:i + 2] in (r'\(', r'\['):
                delim = text[i:i + 2]
                close = r'\)' if delim == r'\(' else r'\]'
                j = i + 2
                while j < len(text):
                    if text.startswith(close, j) and not escaped(text, j):
                        end, body = j + 2, text[i + 2:j]
                        break
                    j += 1
        elif text[i] == '$' and not escaped(text, i):
            delim = '$$' if text.startswith('$$', i) else '$'
            j = i + len(delim)
            while j < len(text):
                if text.startswith(delim, j) and not escaped(text, j):
                    end, body = j + len(delim), text[i + len(delim):j]
                    break
                j += 1
        if end is None:
            i += 1
            continue
        if start < i: yield 'text', text[start:i], '', ''
        yield kind, text[i:end], body, delim
        i = start = end
    if start < len(text): yield 'text', text[start:], '', ''
