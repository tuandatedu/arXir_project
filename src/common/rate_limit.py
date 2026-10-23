"""Rate limiter dùng chung (arXiv ≥ 3s, Semantic Scholar ≥ 1s)."""

from __future__ import annotations


def sleep_until_allowed(min_interval_sec: float, last_call_monotonic: float) -> float:
    """
    Chờ cho đủ khoảng cách giữa 2 request, trả về timestamp monotonic sau khi sleep.

    Cần code bên trong:
    - elapsed = time.monotonic() - last_call_monotonic
    - nếu elapsed < min_interval_sec thì time.sleep phần còn thiếu
    - return time.monotonic() mới
    """
    raise NotImplementedError("TODO(common): sleep_until_allowed")


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: float = 60.0,
    max_retries: int = 5,
) -> object:
    """
    HTTP request có retry cho 429 / 5xx.

    Cần code bên trong:
    - Dùng requests, gắn User-Agent từ config.
    - 429: đọc Retry-After nếu có, không thì exponential backoff.
    - 403 từ arxiv.org: đây là tín hiệu sai mirror — log rõ, đừng spam.
    - Trả requests.Response; caller tự .json() / ghi file.
    """
    raise NotImplementedError("TODO(common): request_with_retry")
