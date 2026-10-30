"""Fetch and normalize Semantic Scholar reference metadata."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

from src.common.config import S2_FIELDS, S2_PAPER_URL
from src.common.ids import normalize_arxiv_id
from src.common.rate_limit import request_with_retry

LOG = logging.getLogger(__name__)


def fetch_s2_references(arxiv_id: str, api_key: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the API's raw references; an unindexed paper has no references here."""
    # Send the optional key as a header; otherwise let the API apply its public quota.
    headers = {}
    api_key = api_key or os.environ.get("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    # Query using the normalized base ID so a version suffix is not sent to S2.
    url = S2_PAPER_URL.format(arxiv_id=normalize_arxiv_id(arxiv_id))
    try:
        # Ask only for fields the corpus needs; this keeps the response compact.
        response = request_with_retry("GET", url, headers=headers,
                                      params={"fields": ",".join(S2_FIELDS)}, max_retries=4)
        try:
            payload = response.json()
        finally:
            response.close()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (404, 400):
            LOG.warning("Semantic Scholar has no indexed record for %s", arxiv_id)
            return []
        raise
    # Some API responses may omit references or return an unexpected structure.
    refs = payload.get("references", []) if isinstance(payload, dict) else []
    if not isinstance(refs, list):
        LOG.warning("Unexpected Semantic Scholar references payload for %s", arxiv_id)
        return []
    return [ref for ref in refs if isinstance(ref, dict)]


def extract_arxiv_id_from_external_ids(external_ids: dict[str, Any] | None) -> Optional[str]:
    """Extract and normalize a reference's arXiv ID, if Semantic Scholar has one."""
    # References without external IDs remain in local data but won't enter the HF table.
    if not isinstance(external_ids, dict):
        return None
    value = external_ids.get("ArXiv") or external_ids.get("arXiv")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        # Normalize URL/prefix/version variants to a stable base arXiv ID.
        return normalize_arxiv_id(value)
    except ValueError:
        # Keep old-style IDs when the API returns them in a parseable archive/number form.
        return value.strip()


def s2_ref_to_local_record(citing_arxiv_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten one S2 reference into a local record, even when it lacks arXiv ID."""
    # S2 authors are objects; retain only their display names for the flat schema.
    authors = raw.get("authors") or []
    author_names = [a.get("name", "") for a in authors
                    if isinstance(a, dict) and a.get("name")]
    # Prefer a full publication date; if missing, store the year as a string.
    publication_date = raw.get("publicationDate")
    year = raw.get("year")
    date = str(publication_date or year or "")
    # Keep nullable arXiv ID and optional venue/year for later analysis.
    return {
        "arxiv_id": normalize_arxiv_id(citing_arxiv_id),
        "ref_title": raw.get("title") or "",
        "ref_authors": author_names,
        "ref_submission_date": date,
        "ref_arxiv_id": extract_arxiv_id_from_external_ids(raw.get("externalIds")),
        "ref_s2_id": str(raw.get("paperId") or ""),
        "venue": raw.get("venue"),
        "year": year,
    }
