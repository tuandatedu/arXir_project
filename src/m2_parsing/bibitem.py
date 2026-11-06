"""Extract local bibliography entries without requiring network metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.common.schemas import BIBTEX_ENTRY_TYPES
from .gather import strip_tex_line_comments


_BIBITEM = re.compile(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DOI = re.compile(r"10\.\d{4,9}/[^\s{},;]+", re.I)
_URL = re.compile(r"https?://[^\s{}]+", re.I)


def _plain(text: str) -> str:
    text = re.sub(r"\\(?:emph|textit|textbf|url|href)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\b", " ", text)
    return re.sub(r"\s+", " ", text.replace("{", "").replace("}", "")).strip(" .;,\n")


def extract_bibitems(tex: str) -> list[dict[str, Any]]:
    """Convert each reachable ``\bibitem`` to a best-effort BibTeX record."""
    tex = strip_tex_line_comments(tex)
    entries: list[dict[str, Any]] = []
    for env in re.finditer(r"\\begin\{thebibliography\}(?:\{[^{}]*\})?(.*?)\\end\{thebibliography\}", tex, re.S):
        body = env[1]
        matches = list(_BIBITEM.finditer(body))
        for index, match in enumerate(matches):
            raw = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
            raw = re.sub(r"(?<!\\)%[^\n]*", " ", raw)
            doi_match = _DOI.search(raw)
            url_match = _URL.search(raw)
            year_match = _YEAR.search(raw)
            title_match = re.search(r"\\(?:emph|textit|textbf|textsl)\s*\{([^{}]+)\}", raw)
            plain = re.sub(r"\b([A-Z])\.", r"\1<period>", _plain(raw))
            pieces = [p.replace("<period>", ".").strip() for p in re.split(r"(?<!\\)[.;]", plain) if p.strip()]
            authors = _split_authors(pieces[0]) if pieces else []
            title = _plain(title_match[1]) if title_match else (pieces[1] if len(pieces) > 1 else None)
            journal_match = re.search(r"\\(?:emph|textit)\s*\{([^{}]+)\}", raw)
            journal = _plain(journal_match[1]) if journal_match and title_match != journal_match else None
            entry = {
                "citation_key": match[1].strip(), "title": title,
                "authors": authors, "year": int(year_match[0]) if year_match else None,
                "doi": doi_match[0].rstrip(".") if doi_match else None,
                "url": url_match[0].rstrip(".,") if url_match else None,
                "journal": journal,
            }
            entry["entry_type"] = infer_entry_type(entry)
            entries.append(entry)
    return entries


def _split_authors(value: str) -> list[str]:
    value = _plain(value)
    return [name.strip() for name in re.split(r"\s+and\s+|\s*,\s*(?=[A-Z][a-z]+\s+[A-Z])", value) if name.strip()]


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


def parse_bib_file(bib_text: str) -> list[dict[str, Any]]:
    """Parse balanced BibTeX entries and the fields needed by the M2 schema."""
    entries: list[dict[str, Any]] = []
    for match in re.finditer(r"@([a-zA-Z]+)\s*([{(])", bib_text):
        typ = match[1].lower()
        if typ in {"comment", "preamble", "string"}:
            continue
        body, _ = _read_group(bib_text, match.end() - 1)
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


def collect_version_bibtex(source_dir: Path, cleaned_tex: str) -> list[dict[str, Any]]:
    """Collect cited TeX entries and referenced .bib files (when reachable)."""
    entries = extract_bibitems(cleaned_tex)
    cleaned_tex = strip_tex_line_comments(cleaned_tex)
    source_dir = Path(source_dir)
    targets: set[Path] = set()
    for group in re.findall(r"\\(?:bibliography|addbibresource)\s*\{([^{}]+)\}", cleaned_tex):
        for name in group.split(","):
            candidate = source_dir / name.strip()
            if not candidate.suffix:
                candidate = candidate.with_suffix(".bib")
            if candidate.is_file() and candidate.resolve().is_relative_to(source_dir.resolve()):
                targets.add(candidate)
            elif "/" not in name and "\\" not in name:
                # arXiv source bundles sometimes place the .bib beside a subfile.
                targets.update(path for path in source_dir.rglob(candidate.name)
                               if path.is_file() and path.resolve().is_relative_to(source_dir.resolve()))
    # Some sources contain an external .bib without an explicit \bibliography command.
    if not targets and not entries:
        targets.update(source_dir.rglob("*.bib"))
    for path in sorted(targets):
        entries.extend(parse_bib_file(path.read_text(encoding="utf-8", errors="replace")))
    return entries
