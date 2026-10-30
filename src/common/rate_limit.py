"""Shared HTTP pacing/retry helpers for APIs without a dedicated client."""
from __future__ import annotations

import email.utils
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from .config import ARXIV_USER_AGENT

LOG = logging.getLogger(__name__)
# Serialize request-start times so concurrent callers cannot bypass the delay.
_pace_lock = threading.Lock()
# Remember the last start separately for the 1-second and 3-second API policies.
_last_start: dict[float, float] = {}
# Store recent S2 request times to enforce its rolling five-minute quota.
_s2_starts: deque[float] = deque()


def sleep_until_allowed(min_interval_sec: float, last_call_monotonic: float) -> float:
    """Wait until the requested interval has elapsed and return a fresh timestamp."""
    # Compute the unelapsed part of the minimum gap from the last request start.
    if min_interval_sec < 0:
        raise ValueError("min_interval_sec must be nonnegative")
    remaining = min_interval_sec - (time.monotonic() - last_call_monotonic)
    if remaining > 0:
        time.sleep(remaining)
    return time.monotonic()


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Honor Retry-After when supplied; otherwise use capped exponential backoff."""
    # Retry-After may be a number of seconds or an HTTP date.
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after:
        try:
            return min(120.0, max(0.0, float(retry_after)))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return min(120.0, max(0.0, (when - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(60.0, float(2 ** attempt))


def request_with_retry(method: str, url: str, *, headers: dict | None = None,
                       params: dict | None = None, timeout: float = 60.0,
                       max_retries: int = 5) -> requests.Response:
    """Make a paced request and retry transient network, 429, and 5xx errors."""
    if max_retries < 0:
        raise ValueError("max_retries must be nonnegative")
    # Supply a descriptive default User-Agent while allowing caller headers to extend it.
    request_headers = {"User-Agent": ARXIV_USER_AGENT}
    if headers:
        request_headers.update(headers)
    # Calls using the same pacing interval share a request-start schedule.
    # arXiv asks for a 3-second gap; other APIs use the common 1-second baseline.
    interval = 3.0 if "arxiv.org" in (urlparse(url).hostname or "").lower() else 1.0
    for attempt in range(max_retries + 1):
        # Hold the short lock only while scheduling a start, not during network I/O.
        with _pace_lock:
            is_s2 = (urlparse(url).hostname or "").lower() == "api.semanticscholar.org"
            if is_s2:
                # The unauthenticated S2 allowance is capped by both 1 req/s
                # and 100 requests in any rolling five-minute window.
                now = time.monotonic()
                while _s2_starts and now - _s2_starts[0] >= 300.0:
                    _s2_starts.popleft()
                if len(_s2_starts) >= 100:
                    time.sleep(max(0.0, 300.0 - (now - _s2_starts[0])))
            previous = _last_start.get(interval, 0.0)
            _last_start[interval] = sleep_until_allowed(interval, previous)
            if is_s2:
                _s2_starts.append(_last_start[interval])
        # Do not retry permanent network errors forever; stop after configured attempts.
        try:
            response = requests.request(method.upper(), url, headers=request_headers,
                                        params=params, timeout=timeout)
        except requests.RequestException:
            if attempt >= max_retries:
                raise
            time.sleep(min(60.0, float(2 ** attempt)))
            continue

        # A 403 from arXiv usually means the wrong host/mirror; retrying can worsen blocking.
        if response.status_code == 403 and "arxiv.org" in (urlparse(url).hostname or "").lower():
            response.close()
            raise requests.HTTPError(
                "arXiv returned 403; use the export.arxiv.org mirror, not arxiv.org", response=response
            )
        # Rate limits and server errors are temporary, so back off and try again.
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            if attempt >= max_retries:
                response.raise_for_status()
                return response
            delay = _retry_delay(response, attempt)
            response.close()
            LOG.warning("HTTP %s from %s; retrying in %.1fs", response.status_code, url, delay)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response
    raise AssertionError("retry loop exited unexpectedly")
