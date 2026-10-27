"""Thread-safe arXiv HTTP client with globally paced request starts.

Workers can wait for HTTP responses and stream source archives concurrently,
but request starts share one minimum-delay gate. Each worker has its own
requests.Session. The gate is NOT held while waiting for a response or while
streaming its body. 429/5xx retry cooldowns are shared between workers.
"""
from __future__ import annotations

from contextlib import contextmanager
import email.utils
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Iterator

import requests

from src.common.config import ARXIV_MIN_DELAY_SEC, ARXIV_USER_AGENT

LOG = logging.getLogger(__name__)


class ArxivHTTPError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ArxivHTTP:
    """Shared request pacing and counters; per-thread sessions.

    All callers use ``with http.get(url, ...) as response``. A short lock
    serializes request-start scheduling, NOT response streaming. Close this
    client only after all worker threads have joined.
    """

    RETRYABLE = (429, 500, 502, 503, 504)

    def __init__(self, delay: float = ARXIV_MIN_DELAY_SEC, timeout: int = 90,
                 retries: int = 4, user_agent: str = ARXIV_USER_AGENT):
        if delay < ARXIV_MIN_DELAY_SEC:
            raise ValueError(f"arXiv request interval must be >= {ARXIV_MIN_DELAY_SEC}s")
        if retries < 0:
            raise ValueError("retries must be >= 0")
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self._state_lock = threading.Lock()
        self._local = threading.local()
        self._sessions: list[requests.Session] = []
        self.last_request: float | None = None
        self._cooldown_until = 0.0
        self.request_count = 0
        self.retry_count = 0

    @property
    def session(self) -> requests.Session:
        """One Session per calling thread; access only under connection lock."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent, "Accept": "*/*"})
            self._local.session = session
            with self._state_lock:
                self._sessions.append(session)
        return session

    def _pace(self) -> None:
        """Called with _state_lock held; applies across every worker."""
        earliest = self._cooldown_until
        if self.last_request is not None:
            earliest = max(earliest, self.last_request + self.delay)
        remaining = earliest - time.monotonic()
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

    @contextmanager
    def get(self, url: str, *, params: dict | None = None,
            stream: bool = False) -> Iterator[requests.Response]:
        if not url.startswith("https://export.arxiv.org/"):
            raise ValueError("Only https://export.arxiv.org is allowed for this client")
        # Session construction happens before the pacing gate so slow setup
        # cannot postpone a reserved request start and distort the schedule.
        session = self.session
        for attempt in range(self.retries + 1):
            wait = 0.0
            # IMPORTANT: only pace and counters are under the shared lock.
            # Neither session.get() nor iter_content() may hold this lock.
            with self._state_lock:
                self._pace()
                self.request_count += 1
            try:
                response = session.get(url, params=params, stream=stream,
                                       timeout=(15, self.timeout),
                                       allow_redirects=True)
            except requests.RequestException as exc:
                if attempt == self.retries:
                    raise ArxivHTTPError(
                        f"Network failure after retries ({url}): {exc}"
                    ) from exc
                wait = min(90.0, max(self.delay, 2 ** (attempt + 1)))
                LOG.warning("Network error %s; retry in %.1fs", exc, wait)
                with self._state_lock:
                    self.retry_count += 1
                    self._cooldown_until = max(self._cooldown_until,
                                               time.monotonic() + wait)
            else:
                if not response.url.startswith("https://"):
                    response.close()
                    raise ArxivHTTPError(f"Insecure source redirect: {response.url}")
                if not response.url.startswith("https://export.arxiv.org/"):
                    LOG.info("Export mirror redirected to %s", response.url)
                if response.status_code in self.RETRYABLE:
                    status = response.status_code
                    retry_after = self._retry_after(response.headers.get("Retry-After"))
                    response.close()
                    if attempt == self.retries:
                        raise ArxivHTTPError(f"HTTP {status} after retries: {url}", status)
                    wait = max(self.delay, min(120.0, retry_after if retry_after is not None
                                               else 2 ** (attempt + 1)))
                    LOG.warning("HTTP %s, retry %s/%s after %.1fs", status,
                                attempt + 1, self.retries, wait)
                    with self._state_lock:
                        self.retry_count += 1
                        self._cooldown_until = max(self._cooldown_until,
                                                   time.monotonic() + wait)
                elif response.status_code >= 400:
                    status = response.status_code
                    response.close()
                    raise ArxivHTTPError(f"HTTP {status}: {url}", status)
                else:
                    try:
                        with response:
                            yield response
                    finally:
                        response.close()
                    return
            if wait:
                time.sleep(wait)
        raise AssertionError("unreachable")

    def close(self) -> None:
        with self._state_lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()

    def __enter__(self) -> "ArxivHTTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
