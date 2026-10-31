"""arXiv targeted ID discovery (batched Atom API, no full-site harvesting).

Compatibility: PaperMeta, fetch_paper_by_id and list_versions keep the skeleton
signatures so the teammate writing corpus.py/pipeline.py can import them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from src.m1_crawling.arxiv_http import ArxivHTTP

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
VERSION_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z][a-z.-]+(?:/[a-z.-]+)?/\d{7})v([1-9]\d*)$", re.I)


@dataclass
class PaperMeta:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str = ""
    latest_version: int = 1
    submission_date: str = ""
    revised_dates: list[str] = field(default_factory=list)
    venue: str | None = None
    categories: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _identifier(text: str) -> tuple[str, int]:
    identifier = urlparse(text.strip()).path.rsplit("/", 1)[-1]
    matched = VERSION_RE.fullmatch(identifier)
    if matched:
        return matched.group(1), int(matched.group(2))
    matched_base = re.fullmatch(r"\d{4}\.\d{4,5}", identifier)
    if matched_base:
        return identifier, 1
    raise ValueError(f"Invalid arXiv Atom identifier: {text!r}")


def _parse_feed(data: bytes) -> dict[str, PaperMeta]:
    root = ET.fromstring(data)
    if root.tag != ATOM + "feed":
        raise ValueError("arXiv API did not return an Atom feed")
    output = {}
    for entry in root.findall(ATOM + "entry"):
        title = " ".join((entry.findtext(ATOM + "title") or "").split())
        # API may place an explanatory error entry rather than an actual paper.
        if title.lower().startswith("error") and not entry.findall(ATOM + "author"):
            continue
        try:
            base, version = _identifier(entry.findtext(ATOM + "id") or "")
        except ValueError:
            continue
        names = [" ".join((author.findtext(ATOM + "name") or "").split())
                 for author in entry.findall(ATOM + "author")]
        names = [name for name in names if name]
        if not names:
            continue
        published = entry.findtext(ATOM + "published") or ""
        updated = entry.findtext(ATOM + "updated") or ""
        published = published[:10] if published else ""
        updated = updated[:10] if updated else ""
        categories = [node.get("term", "") for node in entry.findall(ATOM + "category")]
        metadata = PaperMeta(
            arxiv_id=base, title=title, authors=names,
            abstract=" ".join((entry.findtext(ATOM + "summary") or "").split()),
            latest_version=version, submission_date=published,
            # Last updated date is reliable; intermediate revision dates require
            # querying version-specific Atom entries separately.
            revised_dates=([updated] if version > 1 and updated else []),
            venue=entry.findtext(ARXIV + "journal_ref"),
            categories=categories,
            raw={"atom_updated": updated, "revision_dates_complete": version == 1 or (version == 2 and bool(updated))},
        )
        previous = output.get(base)
        if previous is None or version >= previous.latest_version:
            output[base] = metadata
    return output


def fetch_papers_by_ids(arxiv_ids: list[str], http: ArxivHTTP | None = None) -> dict[str, PaperMeta]:
    """Discover up to 100 IDs in ONE API call, returning only resolved papers.

    A successful HTTP response with an absent ID means 'not_found'. On API
    failure we RAISE rather than falsely marking every ID as nonexistent.
    """
    if not arxiv_ids:
        return {}
    if len(arxiv_ids) > 100:
        raise ValueError("Batch API discovery must use <=100 IDs per call")
    own = http is None
    http = http or ArxivHTTP()
    try:
        with http.get(API_URL, params={"id_list": ",".join(arxiv_ids),
                                       "start": 0, "max_results": len(arxiv_ids)}) as response:
            parsed = _parse_feed(response.content)
        return {paper_id: parsed[paper_id] for paper_id in arxiv_ids if paper_id in parsed}
    finally:
        if own:
            http.close()


def fetch_paper_by_id(arxiv_id: str) -> PaperMeta:
    result = fetch_papers_by_ids([arxiv_id]).get(arxiv_id)
    if result is None:
        raise LookupError(f"arXiv paper does not exist: {arxiv_id}")
    return result


def list_versions(meta: PaperMeta) -> list[int]:
    if meta.latest_version < 1:
        raise ValueError("Invalid latest_version")
    return list(range(1, meta.latest_version + 1))


def enrich_revision_dates(meta: PaperMeta, http: ArxivHTTP | None = None) -> None:
    """Fill intermediate revision dates with version-qualified Atom lookups.

    For v1 the submission date is known; for the latest vN the Atom updated
    date is known. Papers with v3+ need v2..v(N-1) looked up separately so
    ``revised_dates`` holds every revision date in chronological order. When
    arXiv does not expose an intermediate version, the known dates are kept and
    ``raw.revision_dates_complete`` is set to False.
    """
    if meta.latest_version <= 2:
        return
    own = http is None
    http = http or ArxivHTTP()
    try:
        needed = [f"{meta.arxiv_id}v{n}" for n in range(2, meta.latest_version)]
        intermediate: dict[int, str] = {}
        for i in range(0, len(needed), 80):
            chunk = needed[i:i + 80]
            with http.get(API_URL, params={"id_list": ",".join(chunk),
                                           "start": 0, "max_results": len(chunk)}) as response:
                root = ET.fromstring(response.content)
            for entry in root.findall(ATOM + "entry"):
                try:
                    base, ver = _identifier(entry.findtext(ATOM + "id") or "")
                except ValueError:
                    continue
                if base != meta.arxiv_id:
                    continue
                updated = (entry.findtext(ATOM + "updated") or "")[:10]
                if updated:
                    intermediate[ver] = updated
        dates = [intermediate[v] for v in range(2, meta.latest_version) if v in intermediate]
        meta.raw["revision_dates_complete"] = len(dates) == meta.latest_version - 2
        meta.raw["intermediate_version_dates"] = {
            str(ver): date for ver, date in sorted(intermediate.items())
            if 2 <= ver < meta.latest_version}
        latest = meta.raw.get("atom_updated", "")
        meta.revised_dates = dates + ([latest] if latest else [])
    finally:
        if own:
            http.close()


def version_update_date(meta: PaperMeta, version: int) -> tuple[str | None, str]:
    """Return (date, source) for one version from discovery metadata."""
    if version == 1:
        return meta.submission_date or None, "atom_published"
    if version == meta.latest_version:
        return meta.raw.get("atom_updated") or None, "atom_updated_latest"
    dates = meta.raw.get("intermediate_version_dates") or {}
    date = dates.get(str(version))
    return (date or None), ("atom_intermediate_version" if date else "unknown")


def harvest_oai_pmh_optional(date_from: str, date_to: str) -> list[dict[str, Any]]:
    raise NotImplementedError("Optional whole-repository harvest is out of scope for M1")


def load_kaggle_metadata_optional(file_path: str, keyword: str) -> object:
    raise NotImplementedError("Optional Kaggle data is not needed for assigned ID discovery")
