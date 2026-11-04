"""Offline regression tests for bounded concurrent paper processing."""
from __future__ import annotations

import csv
import io
import json
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.m1_crawling import run_arxiv_only as crawler
from src.m1_crawling import arxiv_http
from src.m1_crawling.export_reports import export_reports
from src.m1_crawling.run_arxiv_only import _run_batch

FEED = b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2604.00535v1</id><title>First</title>
  <published>2026-04-01T10:00:00Z</published><updated>2026-04-01T10:00:00Z</updated>
  <author><name>A</name></author></entry>
  <entry><id>http://arxiv.org/abs/2604.00536v1</id><title>Second</title>
  <published>2026-04-01T10:00:00Z</published><updated>2026-04-01T10:00:00Z</updated>
  <author><name>B</name></author></entry>
</feed>'''


class FakeResponse:
    def __init__(self, content):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


class FakeHTTP:
    request_count = 0
    retry_count = 0
    def get(self, url, *, params=None, stream=False):
        return FakeResponse(FEED)


def make_source(dest, text):
    with tarfile.open(dest, "w:gz") as archive:
        content = text.encode()
        info = tarfile.TarInfo("main.tex")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))


def test_concurrent_papers_finish_out_of_order_but_export_in_order(tmp_path, monkeypatch):
    ids = ["2604.00535", "2604.00536"]
    barrier = threading.Barrier(2)
    seen = []
    lock = threading.Lock()

    def download(pid, ver, dest, http=None):
        barrier.wait(timeout=3)  # verifies both papers are running concurrently
        if pid == ids[0]:
            time.sleep(.05)
        make_source(dest, f"\\documentclass{{article}} {pid}")
        with lock:
            seen.append(pid)

    monkeypatch.setattr(crawler, "download_source_archive", download)
    backup = tmp_path / "backup"
    m = _run_batch(ids, "batch_00000", tmp_path / "scratch", backup,
                   FakeHTTP(), False, False, False, workers=2)
    assert m["ok"] == 2 and m["failed"] == 0
    assert seen == list(reversed(ids))
    assert m["processed_this_run"] == 2
    assert m["archive_bytes"] > 0
    summary = export_reports(backup)
    assert summary["total_records"] == 2
    with (backup / "reports" / "crawl_records.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["arxiv_id"] for r in rows] == ids


def test_concurrent_recovery_only_failed_paper_and_keeps_success(tmp_path, monkeypatch):
    ids = ["2604.00535", "2604.00536"]
    calls = []
    failed = {"first": True}

    def download(pid, ver, dest, http=None):
        calls.append(pid)
        if pid == ids[0] and failed["first"]:
            failed["first"] = False
            raise OSError("temporary download failure")
        make_source(dest, "\\documentclass{article}")

    monkeypatch.setattr(crawler, "download_source_archive", download)
    backup = tmp_path / "backup"
    a = _run_batch(ids, "batch_00000", tmp_path / "scratch", backup,
                   FakeHTTP(), False, False, False, workers=2)
    assert a["failed"] == 1
    b = _run_batch(ids, "batch_00000", tmp_path / "scratch", backup,
                   FakeHTTP(), False, True, False, workers=2)
    assert b["failed"] == 0 and b["ok"] == 2
    assert calls.count(ids[0]) == 2
    assert calls.count(ids[1]) == 1
    assert export_reports(backup)["failed_version_rows"] == 0


def test_http_concurrent_streaming_and_global_counters(monkeypatch):
    active = 0
    peak = 0
    guard = threading.Lock()

    class Response:
        url = "https://export.arxiv.org/src/test"
        status_code = 200
        headers = {}
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    class Session:
        def __init__(self):
            self.headers = {}
        def get(self, *args, **kwargs):
            return Response()
        def close(self):
            pass

    monkeypatch.setattr(arxiv_http.requests, "Session", Session)
    http = arxiv_http.ArxivHTTP(delay=3.1, retries=0)
    # This test isolates the connection lock without sleeping 3 seconds.
    monkeypatch.setattr(http, "_pace", lambda: None)

    def worker(_):
        nonlocal active, peak
        with http.get("https://export.arxiv.org/src/test", stream=True):
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(.015)
            with guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(8)))
    assert peak >= 2  # response streams overlap; previously serialized by lock
    assert http.request_count == 8
    assert http.retry_count == 0
    assert len(http._sessions) >= 2
    http.close()


def test_http_global_pacing_and_429_retry_after(monkeypatch):
    clock = [100.0]
    starts = []
    statuses = [429, 200, 200]

    class Response:
        url = "https://export.arxiv.org/src/test"
        def __init__(self, status):
            self.status_code = status
            self.headers = {"Retry-After": "10"} if status == 429 else {}
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    class Session:
        def __init__(self):
            self.headers = {}
        def get(self, *args, **kwargs):
            starts.append(clock[0])
            return Response(statuses.pop(0))
        def close(self):
            pass

    monkeypatch.setattr(arxiv_http.requests, "Session", Session)
    monkeypatch.setattr(arxiv_http.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(arxiv_http.time, "sleep", lambda secs: clock.__setitem__(0, clock[0] + secs))
    with arxiv_http.ArxivHTTP(delay=3.1, retries=1) as http:
        with http.get("https://export.arxiv.org/src/test"):
            pass
        with http.get("https://export.arxiv.org/src/test"):
            pass
        assert http.request_count == 3
        assert http.retry_count == 1
    assert starts == [100.0, 110.0, 113.1]


def test_recovery_cli_never_processes_missing_checkpoint(tmp_path, monkeypatch):
    ids = ["2604.00535", "2604.00536", "2604.00537"]
    monkeypatch.setattr(crawler, "assigned_ids", lambda range_number: ids)
    monkeypatch.setattr(crawler, "_existing_manifest", lambda backup, name, expected_ids,
                        verify_checksum=False: {"failed": 1} if name == "batch_00001" else None)
    calls = []

    class HTTP:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    monkeypatch.setattr(crawler, "ArxivHTTP", HTTP)

    def run_batch(batch_ids, name, *args, **kwargs):
        calls.append((name, kwargs.get("workers")))
        return {"failed": 0}

    monkeypatch.setattr(crawler, "_run_batch", run_batch)
    assert crawler.main(["--range", "5", "--batch-size", "1", "--next", "100",
                         "--workers", "3", "--retry-failed",
                         "--backup-dir", str(tmp_path)]) == 0
    assert calls == [("batch_00001", 3)]


def test_http_pacing_shared_across_workers_while_responses_overlap(monkeypatch):
    # Use a tiny test-only delay, never weaken the production 3.1s default.
    monkeypatch.setattr(arxiv_http, "ARXIV_MIN_DELAY_SEC", 0.025)
    started = []
    in_flight = 0
    peak = 0
    guard = threading.Lock()

    class Response:
        url = "https://export.arxiv.org/src/test"
        status_code = 200
        headers = {}
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    class Session:
        def __init__(self):
            self.headers = {}
        def get(self, *args, **kwargs):
            nonlocal in_flight, peak
            with guard:
                started.append(time.monotonic())
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(.065)  # simulate network wait with lock released
            with guard:
                in_flight -= 1
            return Response()
        def close(self):
            pass

    monkeypatch.setattr(arxiv_http.requests, "Session", Session)
    with arxiv_http.ArxivHTTP(delay=.025, retries=0) as http:
        def worker(_):
            with http.get("https://export.arxiv.org/src/test"):
                pass
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(worker, range(5)))
        assert http.request_count == 5
    assert peak >= 2
    assert len(started) == 5
    assert all(b - a >= .019 for a, b in zip(started, started[1:]))
