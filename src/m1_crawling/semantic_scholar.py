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

# Cumulative HTTP attempt counters for this process, filled by request_with_retry.
_REQUEST_STATS: dict[str, int] = {
    "http_requests": 0,
    "http_retries": 0,
    "http_429": 0,
}


def request_stats() -> dict[str, int]:
    """Return a snapshot of S2 HTTP attempt/retry/429 counters."""
    return dict(_REQUEST_STATS)


def reset_request_stats() -> None:
    """Reset the S2 HTTP counters, e.g. before a fresh benchmark run."""
    for key in _REQUEST_STATS:
        _REQUEST_STATS[key] = 0


def _resolve_api_key(api_key: Optional[str]) -> Optional[str]:
    key = (api_key or os.environ.get("S2_API_KEY") or "").strip()
    return key or None


def _min_delay_sec(has_key: bool) -> float:
    return S2_MIN_DELAY_SEC if has_key else S2_MIN_DELAY_UNAUTH_SEC


def _pace_s2_request(has_key: bool) -> None:
    """
    Điều tiết một lần thử request S2.

    Hàm này được gọi trước MỌI attempt (kể cả retry bên trong
    request_with_retry), nên retry không thể vượt khoảng chờ tối thiểu.
    """
    global _last_call_monotonic, _cooldown_until
    remaining = _cooldown_until - time.monotonic()
    if remaining > 0:
        LOG.info("S2 rate-limit cooldown: sleeping %.0fs", remaining)
        time.sleep(remaining)
    _last_call_monotonic = sleep_until_allowed(
        _min_delay_sec(has_key), _last_call_monotonic)


def fetch_s2_payload_with_status(
    arxiv_id: str,
    api_key: Optional[str] = None,
) -> tuple[Optional[dict[str, Any]], str, str, str]:
    """
    GET một paper S2 và trả (payload, status, error, error_kind).

    status:
    - ok: HTTP 200 + payload là object + có field ``references`` kiểu list
      (list rỗng vẫn là ok).
    - not_indexed: CHỈ HTTP 404 (S2 chưa ghi nhận paper).
    - failed: HTTP 400/429/5xx, lỗi mạng, JSON hỏng, hoặc payload thiếu/sai
      cấu trúc field ``references``.

    error_kind dùng để tách lỗi HTTP/network khỏi lỗi xử lý local:
    http_404, http_400, http_429, http_<code>, network, invalid_json,
    invalid_payload, request_rejected.

    Rate limit/cooldown được áp dụng bên trong request_with_retry qua
    ``before_attempt`` nên cả lần thử đầu và các retry đều được điều tiết.
    KHÔNG dùng nested field `authors.name` (API reject).
    """
    global _cooldown_until
    base = normalize_arxiv_id(arxiv_id)
    url = S2_PAPER_URL.format(arxiv_id=base)
    headers: dict[str, str] = {}
    key = _resolve_api_key(api_key)
    if key:
        headers["x-api-key"] = key
    params = {"fields": ",".join(S2_FIELDS)}
    try:
        response = request_with_retry(
            "GET", url, headers=headers or None, params=params,
            timeout=60.0, max_retries=5,
            before_attempt=lambda: _pace_s2_request(bool(key)),
            stats=_REQUEST_STATS)
    except requests.RequestException as exc:
        LOG.warning("Semantic Scholar network failure for %s: %s", base, exc)
        return None, "failed", f"Network error: {exc}", "network"
    except RuntimeError as exc:
        # HTTP 403 — sai endpoint / bị chặn; không retry dồn dập.
        LOG.error("Semantic Scholar rejected request for %s: %s", base, exc)
        return None, "failed", f"Request rejected: {exc}", "request_rejected"

    status = getattr(response, "status_code", None)
    if status == 404:
        LOG.info("Semantic Scholar has not indexed arXiv:%s yet", base)
        return None, "not_indexed", "HTTP 404 Not Found", "http_404"
    if status == 400:
        LOG.warning("Semantic Scholar rejected arXiv:%s as invalid", base)
        return None, "failed", "HTTP 400 Bad Request", "http_400"
    if status == 429:
        _cooldown_until = time.monotonic() + S2_429_COOLDOWN_SEC
        message = (
            "HTTP 429 rate limit exhausted after retries "
            f"(cooldown {S2_429_COOLDOWN_SEC:.0f}s)")
        LOG.warning("Semantic Scholar %s for arXiv:%s", message, base)
        return None, "failed", message, "http_429"
    if status is None or status >= 400:
        LOG.warning("Semantic Scholar HTTP %s for arXiv:%s", status, base)
        return None, "failed", f"HTTP {status}", f"http_{status}"

    try:
        payload = response.json()
    except ValueError as exc:
        LOG.warning("Semantic Scholar returned non-JSON body for %s: %s",
                    base, exc)
        return None, "failed", f"JSON decode error: {exc}", "invalid_json"
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    if not isinstance(payload, dict):
        LOG.warning("Semantic Scholar returned non-object JSON for %s: %r",
                    base, type(payload).__name__)
        return (None, "failed",
                f"Invalid JSON structure: expected object, got {type(payload).__name__}",
                "invalid_payload")
    if "references" not in payload:
        LOG.warning("Semantic Scholar payload missing 'references' for %s", base)
        return (None, "failed",
                "Missing 'references' field in S2 payload", "invalid_payload")
    references = payload.get("references")
    if not isinstance(references, list):
        LOG.warning("Semantic Scholar 'references' is not a list for %s: %r",
                    base, type(references).__name__)
        return (None, "failed",
                f"Invalid 'references' field: expected list, got {type(references).__name__}",
                "invalid_payload")
    return payload, "ok", "", ""


def _s2_request(arxiv_id: str, api_key: Optional[str]) -> Optional[dict[str, Any]]:
    """Backward-compatible wrapper: trả payload nếu status ok, ngược lại None."""
    payload, status, _, _ = fetch_s2_payload_with_status(arxiv_id, api_key)
    return payload if status == "ok" else None


def extract_reference_objects(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[Any]]:
    """
    Tách reference objects hợp lệ và phần tử sai cấu trúc.

    - Raise ValueError nếu payload thiếu ``references`` hoặc sai kiểu list.
    - Phần tử không phải object được trả riêng để caller ghi nhận, không bị
      bỏ qua âm thầm.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if "references" not in payload:
        raise ValueError("payload missing 'references' field")
    references = payload.get("references")
    if not isinstance(references, list):
        raise ValueError(
            f"'references' must be a list, got {type(references).__name__}")
    valid: list[dict[str, Any]] = []
    invalid: list[Any] = []
    for item in references:
        if isinstance(item, dict):
            valid.append(item)
        else:
            invalid.append(item)
    return valid, invalid


def fetch_s2_references(arxiv_id: str, api_key: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Gọi S2, trả list raw reference objects.

    - URL = S2_PAPER_URL.format(arxiv_id=arxiv_id), params fields=S2_FIELDS.
    - Header x-api-key nếu có (env S2_API_KEY) — unauth: delay 3.1s (100/5 phút);
      có key: delay 1s. Rate-limit áp dụng cho cả retry qua before_attempt.
    - Paper mới / chưa index (404) hoặc request lỗi: trả [] và log rõ, không
      crash pipeline. Missing/wrong ``references`` được log là failed, không
      được coi là list rỗng hợp lệ.
    - KHÔNG dùng nested field `authors.name` (API reject).
    """
    base = normalize_arxiv_id(arxiv_id)
    payload, status, error, error_kind = fetch_s2_payload_with_status(base, api_key)
    if payload is None:
        if status == "failed":
            LOG.warning("Semantic Scholar reference fetch failed for %s (%s): %s",
                        base, error_kind, error)
        return []
    valid, invalid = extract_reference_objects(payload)
    if invalid:
        LOG.warning(
            "Semantic Scholar returned %d non-object reference(s) for %s; "
            "skipped (first: %r)", len(invalid), base, invalid[0])
    return valid


def fetch_s2_references_with_status(
    arxiv_id: str,
    api_key: Optional[str] = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Fetch valid reference objects and preserve the request status."""
    base = normalize_arxiv_id(arxiv_id)
    payload, status, error, error_kind = fetch_s2_payload_with_status(
        base, api_key
    )
    if payload is None:
        if status == "failed":
            LOG.warning(
                "Semantic Scholar reference fetch failed for %s (%s): %s",
                base, error_kind, error,
            )
        return [], status, error
    valid, invalid = extract_reference_objects(payload)
    if invalid:
        return [], "failed", (
            f"Invalid reference item structure: {len(invalid)} non-object item(s)"
        )
    return valid, "ok", ""


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
