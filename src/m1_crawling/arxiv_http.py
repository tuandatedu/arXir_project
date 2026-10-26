"""Single-connection, shared arXiv throttle and bounded HTTP retries.

Never parallelize requests to arXiv from the same crawler. Metadata and source
MUST use the same client, otherwise their independent 3-second timers collide.
"""
from __future__ import annotations

import email.utils
import logging
import time
from datetime import datetime, timezone

import requests

from src.common.config import ARXIV_MIN_DELAY_SEC, ARXIV_USER_AGENT

LOG = logging.getLogger(__name__)


class ArxivHTTPError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ArxivHTTP:
    """Use ONE instance for metadata + source requests in one process."""

    def __init__(self, delay: float = ARXIV_MIN_DELAY_SEC, timeout: int = 90,
                 retries: int = 4, user_agent: str = ARXIV_USER_AGENT):
        if delay < ARXIV_MIN_DELAY_SEC:
            raise ValueError(f"arXiv request interval must be >= {ARXIV_MIN_DELAY_SEC}s")
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})
        self.last_request: float | None = None
        self.request_count = 0
        self.retry_count = 0

    def _pace(self) -> None:
        if self.last_request is not None:
            remaining = self.delay - (time.monotonic() - self.last_request)
            if remaining > 0:
                time.sleep(remaining)
        self.last_request = time.monotonic()

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return None

    def get(self, url: str, *, params: dict | None = None,
            stream: bool = False) -> requests.Response:
        if not url.startswith("https://export.arxiv.org/"):
            raise ValueError("Only https://export.arxiv.org is allowed for this client")
        for attempt in range(self.retries + 1):
            self._pace()
            self.request_count += 1
            try:
                response = self.session.get(url, params=params, stream=stream,
                                            timeout=(15, self.timeout), allow_redirects=True)
                # The export mirror may redirect source binaries to an HTTPS CDN.
                # The initial request MUST target export.arxiv.org; we accept
                # server-directed HTTPS redirects but never follow plaintext HTTP.
                if not response.url.startswith("https://"):
                    response.close()
                    raise ArxivHTTPError(f"Insecure source redirect: {response.url}")
                if not response.url.startswith("https://export.arxiv.org/"):
                    LOG.info("Export mirror redirected to %s", response.url)
                if response.status_code in (429, 500, 502, 503, 504):
                    status = response.status_code
                    retry_after = self._retry_after(response.headers.get("Retry-After"))
                    response.close()
                    if attempt == self.retries:
                        raise ArxivHTTPError(f"HTTP {status} after retries: {url}", status)
                    wait = max(self.delay, min(120.0, retry_after if retry_after is not None else 2 ** (attempt + 1)))
                    LOG.warning("HTTP %s, retry %s/%s after %.1fs", status, attempt + 1, self.retries, wait)
                    self.retry_count += 1
                    time.sleep(wait)
                    continue
                if response.status_code >= 400:
                    status = response.status_code
                    response.close()
                    raise ArxivHTTPError(f"HTTP {status}: {url}", status)
                return response
            except (requests.RequestException,) as exc:
                if attempt == self.retries:
                    raise ArxivHTTPError(f"Network failure after retries ({url}): {exc}") from exc
                wait = min(90.0, max(self.delay, 2 ** (attempt + 1)))
                LOG.warning("Network error %s; retry in %.1fs", exc, wait)
                self.retry_count += 1
                time.sleep(wait)
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ArxivHTTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
