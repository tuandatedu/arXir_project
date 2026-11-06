"""
Crawl reference metadata qua Semantic Scholar Graph API.

Endpoint: https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}
Fields (flat, không nest authors.name): references.title, authors, year,
publicationDate, venue, externalIds.

Bảng Hugging Face `references` CHỈ giữ reference có ArXiv ID.
Working corpus PHẢI lưu mọi reference (kể cả không có arXiv ID).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from src.common.config import (
    S2_429_COOLDOWN_SEC,
    S2_FIELDS,
    S2_MIN_DELAY_SEC,
    S2_MIN_DELAY_UNAUTH_SEC,
    S2_PAPER_URL,
)
from src.common.ids import normalize_arxiv_id
from src.common.rate_limit import request_with_retry, sleep_until_allowed

LOG = logging.getLogger(__name__)

# Pace across every caller in this process (one connection at a time).
_last_call_monotonic = 0.0
# Shared cooldown after a 429 that outlived retries (monotonic deadline).
_cooldown_until = 0.0


def _resolve_api_key(api_key: Optional[str]) -> Optional[str]:
    key = (api_key or os.environ.get("S2_API_KEY") or "").strip()
    return key or None


def _min_delay_sec(has_key: bool) -> float:
    return S2_MIN_DELAY_SEC if has_key else S2_MIN_DELAY_UNAUTH_SEC


def _s2_request(arxiv_id: str, api_key: Optional[str]) -> Optional[dict[str, Any]]:
    """
    GET một paper S2. Trả dict JSON hoặc None nếu không lấy được (đã log).

    Xử lý:
    - 404 / 400 → paper chưa được S2 ghi nhận hoặc ID không hợp lệ → None.
    - 429 sau retry → vượt giới hạn truy vấn → None (không crash pipeline).
    - lỗi mạng sau retry → None.
    KHÔNG dùng nested field `authors.name` (API reject).
    """
    global _last_call_monotonic, _cooldown_until
    url = S2_PAPER_URL.format(arxiv_id=arxiv_id)
    headers: dict[str, str] = {}
    key = _resolve_api_key(api_key)
    if key:
        headers["x-api-key"] = key
    params = {"fields": ",".join(S2_FIELDS)}
    # Đợi hết cooldown 429 chung trước khi request kế tiếp.
    remaining = _cooldown_until - time.monotonic()
    if remaining > 0:
        LOG.info("S2 rate-limit cooldown: sleeping %.0fs", remaining)
        time.sleep(remaining)
    _last_call_monotonic = sleep_until_allowed(
        _min_delay_sec(bool(key)), _last_call_monotonic)
    try:
        response = request_with_retry(
            "GET", url, headers=headers or None, params=params,
            timeout=60.0, max_retries=5)
    except requests.RequestException as exc:
        LOG.warning("Semantic Scholar network failure for %s: %s", arxiv_id, exc)
        return None
    except RuntimeError as exc:
        # HTTP 403 — sai endpoint / bị chặn; không retry dồn dập.
        LOG.error("Semantic Scholar rejected request for %s: %s", arxiv_id, exc)
        return None
    status = getattr(response, "status_code", None)
    if status == 404:
        LOG.info("Semantic Scholar has not indexed arXiv:%s yet", arxiv_id)
        return None
    if status == 400:
        LOG.warning("Semantic Scholar rejected arXiv:%s as invalid", arxiv_id)
        return None
    if status == 429:
        _cooldown_until = time.monotonic() + S2_429_COOLDOWN_SEC
        LOG.warning(
            "Semantic Scholar rate limit exhausted for arXiv:%s "
            "— cooling down %.0fs before next paper",
            arxiv_id, S2_429_COOLDOWN_SEC)
        return None
    if status is None or status >= 400:
        LOG.warning("Semantic Scholar HTTP %s for arXiv:%s", status, arxiv_id)
        return None
    try:
        payload = response.json()
    except ValueError as exc:
        LOG.warning("Semantic Scholar returned non-JSON body for %s: %s",
                    arxiv_id, exc)
        return None
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return payload if isinstance(payload, dict) else None


def fetch_s2_references(arxiv_id: str, api_key: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Gọi S2, trả list raw reference objects.

    - URL = S2_PAPER_URL.format(arxiv_id=arxiv_id), params fields=S2_FIELDS.
    - Header x-api-key nếu có (env S2_API_KEY) — unauth: delay 3.1s (100/5 phút);
      có key: delay 1s. Rate-limit S2_MIN_DELAY_SEC, retry 429 + cooldown chung.
    - Paper mới / chưa index: trả [] và log warning, không crash pipeline.
    - KHÔNG dùng nested field `authors.name` (API reject).
    """
    base = normalize_arxiv_id(arxiv_id)
    payload = _s2_request(base, api_key)
    if payload is None:
        return []
    references = payload.get("references")
    if references is None:
        LOG.info("Semantic Scholar returned no references field for arXiv:%s", base)
        return []
    if not isinstance(references, list):
        LOG.warning("Unexpected references payload for arXiv:%s: %r",
                    base, type(references).__name__)
        return []
    clean: list[dict[str, Any]] = []
    for item in references:
        if isinstance(item, dict):
            clean.append(item)
        else:
            LOG.debug("Skipping non-object reference of arXiv:%s", base)
    return clean


def extract_arxiv_id_from_external_ids(external_ids: dict[str, Any] | None) -> Optional[str]:
    """
    Lấy key 'ArXiv' từ externalIds. Giữ nguyên scheme cũ hep-th/9901001.

    - None / thiếu key → None (reference không vào bảng HF, vẫn lưu local).
    - Bỏ suffix version; không đổi archive/YYMMNNN.
    """
    if not external_ids or not isinstance(external_ids, dict):
        return None
    raw = external_ids.get("ArXiv")
    if not raw or not isinstance(raw, str):
        return None
    try:
        return normalize_arxiv_id(raw)
    except ValueError:
        LOG.debug("Malformed ArXiv externalId on S2 reference: %r", raw)
        return None


def s2_ref_to_local_record(citing_arxiv_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """
    Chuẩn hóa 1 reference S2 thành record local (giữ cả khi không có ArXiv).

    - citing arxiv_id
    - ref_title, ref_authors (list[str] từ objects {authorId, name})
    - ref_submission_date (publicationDate hoặc year)
    - ref_arxiv_id (nullable ở local)
    - ref_s2_id = paperId
    - venue, year (optional, tiện M3)
    """
    authors: list[str] = []
    for author in raw.get("authors") or []:
        if isinstance(author, dict):
            name = author.get("name")
            if isinstance(name, str) and name.strip():
                authors.append(name.strip())
    publication_date = raw.get("publicationDate")
    if isinstance(publication_date, str) and publication_date.strip():
        ref_submission_date = publication_date.strip()[:10]
    elif raw.get("year") is not None:
        ref_submission_date = str(raw["year"])
    else:
        ref_submission_date = ""
    title = raw.get("title")
    venue = raw.get("venue")
    year = raw.get("year")
    return {
        "arxiv_id": normalize_arxiv_id(citing_arxiv_id),
        "ref_title": title.strip() if isinstance(title, str) else "",
        "ref_authors": authors,
        "ref_submission_date": ref_submission_date,
        "ref_arxiv_id": extract_arxiv_id_from_external_ids(raw.get("externalIds")),
        "ref_s2_id": str(raw.get("paperId") or ""),
        "venue": venue.strip() if isinstance(venue, str) and venue.strip() else None,
        "year": year if isinstance(year, int) else None,
    }
