"""Extract local bibliography entries without requiring network metadata."""

from __future__ import annotations

import re
import logging
import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.common.schemas import BIBTEX_ENTRY_TYPES
from .gather import active_tex, strip_tex_line_comments
from .tex_spans import group, spans

LOG = logging.getLogger(__name__)


_BIBITEM = re.compile(r"\\bibitem\b\s*(?:\[(?:[^\[\]]|\[[^\[\]]*\])*\]\s*)?\{([^{}]+)\}")
_YEAR = re.compile(r"(?<!\d)(?:1[5-9]|20)\d{2}(?!\d)")
_DOI = re.compile(r"10\.\d{4,9}/[^\s{},;]+", re.I)
_URL = re.compile(r"https?://[^\s{}]+", re.I)
_CITATIONS = re.compile(r"\\(?:[A-Za-z]*cite[A-Za-z]*|nocite)\*?(?:\s*\[[^\]]*\])*\s*\{([^{}]+)\}", re.I)
_LOCATOR = re.compile(
    r"(?i)^(?:(?:pp?|vol(?:ume)?|no|iss(?:ue)?)\.?\s*)?\d"
    r"|^(?:19|20)\d{2}\b"
    r"|^\((?:19|20)\d{2}\)"
)
_INITIALS_LAST = r"(?:[A-Z]\.(?:-?[A-Z]\.)?\s*)+[A-Z][\w'’-]+"
_FIRST_LAST = r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*)+"
_LAST_INITIALS = r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*,\s*(?:[A-Z]\.\s*)+"
_NAME = rf"(?:et\s+al\.?|{_INITIALS_LAST}|{_FIRST_LAST}|{_LAST_INITIALS})"
_AUTHORS_HEAD = re.compile(
    rf"^(?P<authors>{_NAME}(?:\s*,\s*{_NAME})*(?:\s*(?:,\s*)?(?:and|&)\s+{_NAME})?)\s*,\s+(?P<rest>.+)$",
    re.S,
)
_VENUE_TAIL = re.compile(
    r"(?P<title>.+?),\s+(?P<venue>(?:in\s+)?(?:[A-Z][\w.&'’-]*|of|the|and|for|in|on|at|de|der|la|und|et)"
    r"(?:\s+(?:[A-Z][\w.&'’-]*|\.?of|the|and|for|in|on|at|de|der|la|und|et))*"
    r"\.?\s+\d+.*)$"
)
_TRAILING_DOI = re.compile(r"(?i)\s*doi:\s*\S+\s*$")
_TRAILING_YEAR = re.compile(r"\s*(?:\((?:19|20)\d{2}\)|\b(?:19|20)\d{2})\.?\s*$")


@lru_cache(maxsize=1)
def _text_decoder():
    from pylatexenc.latex2text import LatexNodes2Text
    return LatexNodes2Text()


@lru_cache(maxsize=16384)
def _plain(text: str) -> str:
    # Decode accents without stripping their letters, and keep title math intact.
    text = _unwrap_bib_fields(text)
    text = re.sub(r"\\(?:emph|textit|textbf|url|href)\s*\{([^{}]*)\}", r"\1", text)
    decoder = _text_decoder()
    chunks = []
    for kind, raw, _, _ in spans(text):
        if kind == 'math':
            chunks.append(raw)
        elif not any(c in raw for c in '\\{}~'):
            chunks.append(raw)
        else:
            try:
                chunks.append(decoder.latex_to_text(raw))
            except (IndexError, ValueError, TypeError):
                # A publisher-specific/malformed macro must not discard a
                # publication. Preserve evidence instead of inventing text.
                chunks.append(raw)
    return re.sub(r'\s+', ' ', ''.join(chunks).replace('~', ' ')).strip(' .;,\n')


def _unwrap_bib_fields(text: str) -> str:
    pattern = re.compile(r'\\(?:bibinfo|bibfield)\s*\{[^{}]*\}\s*')
    while match := pattern.search(text):
        found = group(text, match.end())
        if found is None: break
        value, end = found
        text = text[:match.start()] + value + text[end:]
    # REVTeX uses these font wrappers around individual name components.
    return re.sub(r'\\(?:bibfnamefont|bibnamefont|citenamefont)\b', '', text)


def _bibitem_year(raw: str) -> int | None:
    explicit = re.search(r'\\bibinfo\s*\{year\}\s*\{(\d{4})\}', raw)
    if explicit: return int(explicit[1])
    visible = _unwrap_bib_fields(raw)
    visible = _URL.sub('', visible)
    visible = _DOI.sub('', visible)
    visible = re.sub(r'(?i)arxiv\s*:\s*[\w./-]+', '', visible)
    parenthesized = re.findall(r'\(\s*((?:1[5-9]|20)\d{2})[a-z]?\s*\)', visible)
    if parenthesized:
        years = set(parenthesized)
        return int(parenthesized[0]) if len(years) == 1 else None
    # A bare year is accepted at a field boundary, never inside title prose.
    candidates = re.findall(r'(?:^|[,.;]\s*|\\newblock\s*)((?:1[5-9]|20)\d{2})[a-z]?(?=\s*(?:[,.;]|$))', visible)
    return int(candidates[0]) if len(set(candidates)) == 1 else None


def extract_bibitems(tex: str) -> list[dict[str, Any]]:
    """Extract \\bibitem metadata conservatively, retaining real titles.

    Common LaTeX/natbib form is ``Authors. \\newblock Title.
    \\newblock \\emph{Journal}, Year.``. An emphasized journal is not
    evidence that it is the title of a paper.
    """
    tex = active_tex(tex)  # hide verbatim, comments, and known inactive TeX
    entries: list[dict[str, Any]] = []
    for env in re.finditer(r"\\begin\s*\{thebibliography\}\s*(?:\{[^{}]*\})?(.*?)\\end\s*\{thebibliography\}", tex, re.S):
        body = env[1]
        matches = list(_BIBITEM.finditer(body))
        for index, match in enumerate(matches):
            raw = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
            raw = re.sub(r"(?<!\\)%[^\n]*", " ", raw).strip()
            doi_match = _DOI.search(raw)
            url_match = _URL.search(raw)
            year = _bibitem_year(raw)
            blocks = [part.strip(" \n.;,") for part in re.split(r"\\newblock\b", raw) if part.strip(" \n.;,")]
            authors: list[str] = []
            title: str | None = None
            venue = ""
            from .bibliography_fields import parse_explicit_bibitem
            explicit = parse_explicit_bibitem(raw)
            if explicit is not None:
                authors, title, venue = explicit
            elif len(blocks) >= 2:
                authors = _split_authors(blocks[0])
                second = blocks[1].strip()
                if len(blocks) >= 3 or not re.match(r"(?i)^(?:in\s+)?\\(?:emph|textit)\s*\{", second):
                    title = _plain(second) or None
                venue = " ".join(blocks[2:]) if len(blocks) >= 3 else (second if title is None else "")
            elif blocks:
                # One-block REVTeX/AMS lines: never treat "Trans. 44" / "Math. 128"
                # as a sentence boundary, and keep "and" inside the title out of authors.
                authors, title, venue = _parse_one_block(blocks[0])
            # When one-block parsing cannot separate a name from metadata,
            # leave the field unknown and retain evidence for manual review.
            suspicious = any(re.search(r'https?://|\b\d{3,}\b|\b(?:Journal|Phys\.|Math\.|arXiv)', a) or len(a) > 160 for a in authors)
            if suspicious:
                authors = []
            journal = _journal_from_venue(venue)
            is_arxiv = bool(re.search(r"(?i)arxiv\s*(?:preprint|:)", venue))
            if journal and (is_arxiv or re.search(r"(?i)^\s*in\s+", venue)):
                journal = None
            entry_type = "inproceedings" if re.search(r"(?i)^\s*in\s+", venue) else ("article" if journal else "misc")
            if explicit is not None and title and re.search(r'(?i)ISBN|monographs|University\s+Press', raw) and not re.match(r'(?i)^\s*in\b', venue):
                entry_type = 'book'
                journal = None
            entries.append({
                "citation_key": match[1].strip(), "title": title,
                "authors": authors, "year": year,
                "doi": doi_match[0].rstrip(".,)") if doi_match else None,
                "url": url_match[0].rstrip(".,)") if url_match else None,
                "journal": journal, "entry_type": entry_type,
                "_raw_bibitem": raw,
                "_parse_warnings": [name for name, present in (
                    ('missing_title', bool(title)), ('missing_authors', bool(authors)),
                    ('uncertain_year', year is not None)) if not present],
            })
    return entries


def _bib_display(text: str) -> str:
    text = _unwrap_bib_fields(text)
    text = re.sub(r"\\(?:emph|textit|textbf|textsl|textrm|textsf)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:em|it|sl|bf|bfseries|itshape|slshape)\b", " ", text)
    return _plain(text)


def _is_locator(text: str) -> bool:
    return bool(_LOCATOR.match(_plain(text)))


def _peel_locator(text: str) -> tuple[str, str]:
    loc: list[str] = []
    body = text.strip()
    body, n = _TRAILING_DOI.subn("", body)
    if n:
        loc.append("doi")
    body, n = _TRAILING_YEAR.subn("", body)
    if n:
        loc.append("year")
    return body.strip(" .;,"), " ".join(loc)


def _protect_bib_periods(text: str) -> str:
    text = re.sub(r"\b([A-Z])\.", r"\1<period>", text)
    # Journal chains such as Phys. Rev. Lett. 123 or Dalton Trans. 44.
    return re.sub(
        r"\b([A-Z][a-z]{1,8})\.(?=\s+(?:[A-Z][a-z]{0,8}\.|\d))",
        r"\1<period>",
        text,
    )


def _period_pieces(display: str) -> list[str]:
    protected = _protect_bib_periods(display)
    return [
        part.replace("<period>", ".").strip()
        for part in re.split(r"(?<!\\)\.\s+(?=[A-Z\\])", protected)
        if part.strip()
    ]


def _parse_one_block(raw: str) -> tuple[list[str], str | None, str]:
    structured = {}
    for match in re.finditer(r'\\bibinfo\s*\{(title|journal|author)\}\s*', raw):
        found = group(raw, match.end())
        if found: structured.setdefault(match[1], []).append(_plain(found[0]))
    if structured:
        return structured.get('author', []), next(iter(structured.get('title', [])), None), ' '.join(structured.get('journal', []))
    display = _bib_display(raw)
    emphasis = re.search(r'\\(?:emph|textit)\s*', raw)
    if emphasis:
        found = group(raw, emphasis.end())
        prefix = _plain(raw[:emphasis.start()])
        # Explicit author + emphasized title; an emphasized venue after
        # an already delimited title is handled by the existing parser.
        if found and re.fullmatch(rf'{_NAME}(?:\s*(?:,|and|&)\s*{_NAME})*', prefix):
            return _split_authors(prefix), _plain(found[0]), raw[found[1]:].strip(' ,.;')
    # Explicit quoted titles delimit author/year, title and venue reliably.
    quoted = re.search(r"``(.*?)''|“(.*?)”|\"([^\"]+)\"", display, re.S)
    if quoted:
        author_text = re.sub(r'\(\s*\d{4}[a-z]?\s*\)', '', display[:quoted.start()])
        return _split_authors(author_text.strip(' ,.;:')), next(x for x in quoted.groups() if x is not None).strip(' .,'), display[quoted.end():].strip(' ,.;')
    # REVTeX/BibTeX2HTML may expose explicit fields within a single block.
    structured = {}
    for match in re.finditer(r'\\bibinfo\s*\{(title|journal|author)\}\s*', raw):
        found = group(raw, match.end())
        if found: structured.setdefault(match[1], []).append(_plain(found[0]))
    if structured:
        return structured.get('author', []), next(iter(structured.get('title', [])), None), ' '.join(structured.get('journal', []))
    revtex = _parse_revtex_comma(display)
    if revtex is not None:
        return revtex
    # Some AMS entries omit a period after the author; consume names only.
    names = re.match(rf'(?P<authors>{_INITIALS_LAST}(?:\s*(?:,|and|&)\s*{_INITIALS_LAST})*)\s+(?P<rest>[A-Z].+)', display)
    if names:
        rest = names['rest']
        venue_match = _VENUE_TAIL.match(rest)
        if venue_match:
            return _split_authors(names['authors']), venue_match['title'].strip(' .,'), venue_match['venue']
        return _split_authors(names['authors']), _peel_locator(rest)[0] or None, ''
    pieces = _period_pieces(display)
    venue_bits: list[str] = []
    while len(pieces) > 1 and _is_locator(pieces[-1]):
        venue_bits.insert(0, pieces.pop())
    authors = _split_authors(pieces[0]) if pieces else []
    title = None
    venue = " ".join(venue_bits)
    if len(pieces) >= 2 and not _is_locator(pieces[1]):
        title, tail = _peel_locator(pieces[1])
        extra = [tail, *pieces[2:], venue]
        venue = " ".join(x for x in extra if x and x not in {"doi", "year"})
    elif len(pieces) > 2:
        venue = " ".join([*pieces[2:], venue]).strip()
    return authors, title or None, venue


def _parse_revtex_comma(display: str) -> tuple[list[str], str | None, str] | None:
    match = _AUTHORS_HEAD.match(display)
    if not match:
        return None
    rest = match["rest"].strip()
    if re.match(r'^(?:J\.|Phys\.|Rev\.|Math\.|Ann\.|Proc\.|Science\b|Nature\b|Helvetica\b)', rest):
        return _split_authors(match['authors']), None, rest
    venue_match = _VENUE_TAIL.match(rest)
    if venue_match:
        title = venue_match["title"].strip(" .;,")
        if title and not _is_locator(title):
            return _split_authors(match["authors"]), title, venue_match["venue"].strip()
    title, tail = _peel_locator(rest)
    if title and not _is_locator(title):
        venue = "" if tail in {"", "doi", "year"} else tail
        return _split_authors(match["authors"]), title, venue
    return None


def _journal_from_venue(venue: str) -> str | None:
    journal_match = re.search(r"\\(?:emph|textit|textsl)\s*\{([^{}]+)\}", venue)
    if journal_match:
        name = _plain(journal_match[1])
    else:
        plain = _plain(venue)
        found = re.match(r"(.+?)\s+\d+", plain)
        name = found[1].strip(" .;,") if found else ""
    return name or None


def _split_authors(value: str) -> list[str]:
    value = re.sub(r"\s*,\s*$", "", _plain(value))
    parts = re.split(
        r"\s+(?:and|&)\s+|\s*,\s*(?=(?:[A-Z]\.\s*)+[A-Z]|[A-Z][a-z]+\s+[A-Z]|(?i:et\s+al))",
        value,
    )
    return [name.strip(" ,") for name in parts if name.strip(" ,")]


def _read_group(text: str, start: int) -> tuple[str, int]:
    opener = text[start]
    closer = "}" if opener == "{" else ")"
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == opener and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif text[index] == closer and (index == 0 or text[index - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    return text[start + 1:], len(text)


def _parse_bib_file_balanced(bib_text: str) -> list[dict[str, Any]]:
    """Parse balanced BibTeX entries and the fields needed by the M2 schema."""
    entries: list[dict[str, Any]] = []
    pattern = re.compile(r"@([a-zA-Z]+)\s*([{(])")
    entry_pos = 0
    while match := pattern.search(bib_text, entry_pos):
        typ = match[1].lower()
        body, next_pos = _read_group(bib_text, match.end() - 1)
        entry_pos = max(next_pos, match.end())
        # Advance past the entire balanced entry. Otherwise a literal
        # @article inside @comment or another field would become a ghost ref.
        if typ in {"comment", "preamble", "string"}:
            continue
        head, sep, fields_text = body.partition(",")
        if not sep or not head.strip():
            continue
        fields: dict[str, str] = {}
        field_re = re.compile(r"([a-zA-Z][\w-]*)\s*=\s*", re.S)
        pos = 0
        while found := field_re.search(fields_text, pos):
            pos = found.end()
            if pos >= len(fields_text):
                break
            if fields_text[pos] in "{(":
                value, pos = _read_group(fields_text, pos)
            elif fields_text[pos] == '"':
                end = pos + 1
                while end < len(fields_text) and (fields_text[end] != '"' or fields_text[end - 1] == "\\"):
                    end += 1
                value, pos = fields_text[pos + 1:end], end + 1
            else:
                end = fields_text.find(",", pos)
                end = len(fields_text) if end < 0 else end
                value, pos = fields_text[pos:end].strip(), end
            fields[found[1].lower()] = value.strip()
        year = _YEAR.search(fields.get("year", ""))
        entries.append({
            "citation_key": head.strip(),
            "entry_type": typ if typ in BIBTEX_ENTRY_TYPES else infer_entry_type(fields),
            "title": _plain(fields["title"]) if fields.get("title") else None,
            "authors": _split_authors(fields.get("author", "")),
            "year": int(year[0]) if year else None,
            "doi": _plain(fields["doi"]) if fields.get("doi") else None,
            "journal": _plain(fields["journal"]) if fields.get("journal") else None,
            "url": _plain(fields["url"]) if fields.get("url") else None,
        })
    return entries


def infer_entry_type(fields: dict[str, Any]) -> str:
    if fields.get("journal"):
        return "article"
    if fields.get("booktitle"):
        return "inproceedings"
    return "misc"


def _split_bib_authors(value: str) -> list[str]:
    """BibTeX 'and' separates authors only outside protected brace groups."""
    parts, start, depth, i = [], 0, 0, 0
    while i < len(value):
        if value[i] == '{': depth += 1
        elif value[i] == '}': depth -= 1
        match = re.match(r'\s+and\s+', value[i:], re.I) if depth == 0 else None
        if match:
            parts.append(value[start:i]); i += match.end(); start = i
        else: i += 1
    parts.append(value[start:])
    return [_plain(part) for part in parts if part.strip()]


def _parse_bib_file_uncached(bib_text: str) -> list[dict[str, Any]]:
    """Resolve @string and concatenation with the installed BibTeX parser."""
    import bibtexparser
    from bibtexparser.bparser import BibTexParser
    from bibtexparser.bibdatabase import UndefinedString
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    # Resolve each field separately: one missing journal @string must not
    # discard every title/author/year from the bibliography.
    parser.interpolate_strings = False
    database = bibtexparser.loads(bib_text, parser=parser)
    rows = []
    for entry in database.entries:
        fields, warnings = {}, []
        for key, value in entry.items():
            try:
                fields[key.lower()] = str(value.get_value() if hasattr(value, 'get_value') else value)
            except UndefinedString:
                fields[key.lower()] = ''
                warnings.append('undefined_bibtex_string:' + key.lower())
        year = _YEAR.fullmatch(fields.get('year', '').strip())
        rows.append({
            'citation_key': entry['ID'],
            'entry_type': entry['ENTRYTYPE'] if entry['ENTRYTYPE'] in BIBTEX_ENTRY_TYPES else infer_entry_type(fields),
            'title': _plain(fields['title']) if fields.get('title') else None,
            'authors': _split_bib_authors(fields.get('author', '')),
            'year': int(year[0]) if year else None,
            'doi': fields.get('doi') or None,
            'journal': _plain(fields['journal']) if fields.get('journal') else None,
            'url': fields.get('url') or None,
            '_source_format': 'bibtex',
            '_parse_warnings': warnings,
            '_raw_bibitem': repr(entry) if warnings else '',
        })
    return rows


@lru_cache(maxsize=8)
def _cached_bib_file(text: str):
    return _parse_bib_file_uncached(text)


def parse_bib_file(bib_text: str) -> list[dict[str, Any]]:
    if len(bib_text)>1_000_000: return _parse_bib_file_uncached(bib_text)
    return copy.deepcopy(_cached_bib_file(bib_text))


def _selected_bibtex(text: str, cited: set[str]) -> str:
    """Read balanced blocks cheaply, parsing only cited entries and @strings.

    Large shared .bib libraries often contain thousands of unused records.
    Keep string definitions in source order, including those after an entry.
    """
    blocks=[];pos=0
    pattern=re.compile(r'@([a-zA-Z]+)\s*([{(])')
    while match:=pattern.search(text,pos):
        body,end=_read_group(text,match.end()-1)
        pos=max(end,match.end())
        typ=match[1].lower()
        key=body.partition(',')[0].strip()
        if typ=='string' or (typ not in {'comment','preamble'} and key in cited):
            blocks.append(text[match.start():end])
    return '\n'.join(blocks)


def citation_keys(tex: str) -> set[str]:
    if '\\' not in tex or not _CITATIONS.search(tex): return set()
    return {key.strip() for value in _CITATIONS.findall(active_tex(tex))
            for key in value.split(',') if key.strip() and key.strip() != '*'
            and not re.search(r'[#\\{}]', key)}


def collect_version_bibtex(source_dir: Path, cleaned_tex: str) -> list[dict[str, Any]]:
    """Collect cited TeX entries and referenced .bib files (when reachable)."""
    entries = extract_bibitems(cleaned_tex)
    cleaned_tex = active_tex(cleaned_tex)
    cited = {key.strip() for group in _CITATIONS.findall(cleaned_tex)
             for key in group.split(",") if key.strip()}
    use_all = not cited or "*" in cited
    source_dir = Path(source_dir)
    targets: set[Path] = set()
    bibliography_names = re.findall(r"\\(?:bibliography|addbibresource)(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}", cleaned_tex)
    bbl_targets = set()
    for names in bibliography_names:
        for name in names.split(","):
            candidate = source_dir / name.strip()
            if not candidate.suffix:
                candidate = candidate.with_suffix(".bib")
            if candidate.is_file() and candidate.resolve().is_relative_to(source_dir.resolve()):
                targets.add(candidate)
            elif "/" not in name and "\\" not in name:
                # arXiv source bundles sometimes place the .bib beside a subfile.
                targets.update(path for path in source_dir.rglob(candidate.name)
                               if path.is_file() and path.resolve().is_relative_to(source_dir.resolve()))
            bbl = candidate.with_suffix('.bbl')
            if bbl.is_file() and bbl.resolve().is_relative_to(source_dir.resolve()): bbl_targets.add(bbl)
    for name in re.findall(r'\\input\s*\{([^{}]+\.bbl)\}', cleaned_tex):
        bbl = source_dir / name
        if bbl.is_file() and bbl.resolve().is_relative_to(source_dir.resolve()): bbl_targets.add(bbl)
    # A source bundle may omit its bibliography command. Only recover a .bib
    # when at least one actual \cite key matches; never import every unused
    # entry simply because the .bib exists in the archive.
    if not targets and not entries and cited and "*" not in cited:
        for path in source_dir.rglob("*.bib"):
            if not path.is_file():
                continue
            try:
                keys = set(re.findall(r"@\w+\s*[({]\s*([^,\s]+)",
                                      path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
            if keys & cited:
                targets.add(path)
    for path in sorted(targets):
        bib_text=path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_bib_file(bib_text if use_all else _selected_bibtex(bib_text,cited))
        entries.extend(entry for entry in parsed if use_all or entry["citation_key"] in cited)
    # A .bbl is named after the compilation job, not necessarily the .bib.
    # Recover only actual cited keys from other .bbl files; no unused imports.
    other_bbl = {p for p in source_dir.rglob('*') if p.is_file() and p.suffix.lower() == '.bbl'
                 and p.resolve().is_relative_to(source_dir.resolve())}
    for path in sorted(bbl_targets | other_bbl):
        parsed = extract_bibitems(path.read_text(encoding='utf8', errors='replace'))
        entries.extend(e for e in parsed if e['citation_key'] in cited or (use_all and path in bbl_targets))
    # Prefer structured .bib metadata for a key and fill only absent fields.
    by_key = {}
    for entry in sorted(entries, key=lambda e: e.get('_source_format') != 'bibtex'):
        key = entry['citation_key']
        if not use_all and key not in cited: continue
        row = by_key.setdefault(key, dict(entry))
        for field, value in entry.items():
            if not row.get(field) and value: row[field] = value
    return list(by_key.values())
