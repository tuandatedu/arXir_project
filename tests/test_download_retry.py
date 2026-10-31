"""A connection that breaks mid-body must be retried, not recorded as a permanent error."""
from contextlib import contextmanager

import pytest
import requests

from src.m1_crawling import download


class FlakyHTTP:
    def __init__(self, failures, exc):
        self.failures, self.exc, self.calls = failures, exc, 0

    @contextmanager
    def get(self, url, *, params=None, stream=False):
        self.calls += 1
        broken = self.calls <= self.failures
        exc = self.exc

        class Response:
            def iter_content(self, chunk_size):
                yield b"abc"
                if broken:
                    raise exc
                yield b"def"
        yield Response()


def test_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda s: None)
    http = FlakyHTTP(2, requests.exceptions.ChunkedEncodingError("IncompleteRead"))
    out = download.download_source_archive("2603.15583", 1, tmp_path / "a.bin", http=http)
    assert out.read_bytes() == b"abcdef" and http.calls == 3
    assert not (tmp_path / "a.bin.partial").exists()


def test_gives_up_after_attempts_and_cleans_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda s: None)
    http = FlakyHTTP(99, requests.exceptions.ChunkedEncodingError("IncompleteRead"))
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        download.download_source_archive("2603.15583", 1, tmp_path / "a.bin", http=http)
    assert http.calls == download.STREAM_ATTEMPTS
    assert list(tmp_path.iterdir()) == []


def test_size_limit_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda s: None)
    http = FlakyHTTP(0, None)
    with pytest.raises(ValueError):
        download.download_source_archive("2603.15583", 1, tmp_path / "a.bin", http=http, max_bytes=2)
    assert http.calls == 1
