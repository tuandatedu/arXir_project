"""Rate limiter dùng chung (arXiv ≥ 3s, Semantic Scholar ≥ 1s)."""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urlparse

import requests

from src.common.config import ARXIV_USER_AGENT

LOG = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def sleep_until_allowed(min_interval_sec: float, last_call_monotonic: float) -> float:
    """
    Chờ cho đủ khoảng cách giữa 2 request, trả về timestamp monotonic sau khi sleep.
    """
    if min_interval_sec < 0:
        raise ValueError("min_interval_sec must be non-negative")
    elapsed = time.monotonic() - last_call_monotonic
    if elapsed < min_interval_sec:
        time.sleep(min_interval_sec - elapsed)
    return time.monotonic()


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _bump(stats: dict[str, int] | None, key: str) -> None:
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: float = 60.0,
    max_retries: int = 5,
    before_attempt: Callable[[], None] | None = None,
    stats: dict[str, int] | None = None,
) -> object:
    """
    HTTP request có retry cho 429 / 5xx.

    - Dùng requests, gắn User-Agent từ config.
    - 429: đọc Retry-After nếu có, không thì exponential backoff.
    - 403 từ arxiv.org: đây là tín hiệu sai mirror — log rõ, đừng spam.
    - before_attempt (optional): gọi trước MỖI lần thử, kể cả retry. Dùng cho
      rate limiter của caller (ví dụ Semantic Scholar) để retry không vượt
      khoảng chờ tối thiểu.
    - stats (optional): dict được cộng dồn ``http_requests`` (mỗi attempt),
      ``http_retries`` (mỗi lần thử lại) và ``http_429`` (mỗi response 429).
    - Trả requests.Response; caller tự .json() / ghi file.
    - Lỗi mạng sau khi hết retry → raise requests.RequestException.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    merged_headers = {"User-Agent": ARXIV_USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_exception: requests.RequestException | None = None
    for attempt in range(max_retries + 1):
        wait = 0.0
        _bump(stats, "http_requests")
        if before_attempt is not None:
            before_attempt()
        try:
            response = requests.request(
                method, url, headers=merged_headers, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_exception = exc
            if attempt == max_retries:
                raise
            _bump(stats, "http_retries")
            wait = min(90.0, 2 ** attempt or 1.0)
            LOG.warning("Network error on %s (%s); retry in %.1fs", url, exc, wait)
        else:
            if response.status_code == 429:
                _bump(stats, "http_429")
            host = (urlparse(url).hostname or "").lower()
            if response.status_code == 403 and host.endswith("arxiv.org"):
                response.close()
                raise RuntimeError(
                    f"HTTP 403 from {url}: wrong mirror or blocked User-Agent. "
                    "Use https://export.arxiv.org for arXiv traffic.")
            if response.status_code in RETRYABLE_STATUS and attempt < max_retries:
                _bump(stats, "http_retries")
                retry_after = _retry_after_seconds(response)
                response.close()
                wait = min(120.0, retry_after if retry_after is not None
                           else (2 ** attempt or 1.0))
                # 429 là expected khi vượt rate limit — debug để không spam log.
                if response.status_code == 429:
                    LOG.debug("HTTP 429 on %s; retry in %.1fs", url, wait)
                else:
                    LOG.warning("HTTP %s on %s; retry in %.1fs",
                                response.status_code, url, wait)
            elif response.status_code in RETRYABLE_STATUS:
                # Hết retry nhưng vẫn 429/5xx: trả response cho caller tự xử lý.
                return response
            else:
                return response
        if wait:
            time.sleep(wait)
    if last_exception is not None:
        raise last_exception
    raise AssertionError("unreachable")
