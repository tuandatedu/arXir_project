"""Offline tests for the shared S2 batch runner used by the Colab notebook."""

from __future__ import annotations

import json
import time

import pytest

from src.m1_crawling import semantic_scholar as s2
from src.m1_crawling.s2_batch import (
    cache_path_for,
    find_empty_cache_ids,
    read_cached_records,
    run_s2_batch,
    summarize_s2_results,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def close(self):
        return None


def _papers(*arxiv_ids):
    return [{"arxiv_id": arxiv_id} for arxiv_id in arxiv_ids]


def _install_fake_http(monkeypatch, responses):
    pacing_calls = []

    def fake_request(method, url, **kwargs):
        kwargs["before_attempt"]()
        arxiv_id = url.rsplit("arXiv:", 1)[-1]
        return responses[arxiv_id]

    monkeypatch.setattr(s2, "request_with_retry", fake_request)
    monkeypatch.setattr(
        s2, "_pace_s2_request", lambda has_key: pacing_calls.append(has_key))
    return pacing_calls


def test_batch_validates_payload_paces_every_attempt_and_caches(tmp_path, monkeypatch):
    responses = {
        "2310.00001": _FakeResponse(200, {"references": []}),
        "2310.00002": _FakeResponse(200, {}),
        "2310.00003": _FakeResponse(200, {"references": {}}),
        "2310.00004": _FakeResponse(200, {"references": [{"paperId": "r1"}]}),
        "2310.00005": _FakeResponse(404, {}),
        "2310.00006": _FakeResponse(200, {"references": ["not-an-object"]}),
        "2310.00007": _FakeResponse(500, {}),
    }
    pacing_calls = _install_fake_http(monkeypatch, responses)

    results, n_invalid_ids = run_s2_batch(
        _papers(*responses),
        tmp_path,
        progress_every=100,
        progress=lambda *_: None,
    )

    assert n_invalid_ids == 0
    assert len(pacing_calls) == len(responses)
    by_id = {row["arxiv_id"]: row for row in results}

    assert by_id["2310.00001"]["status"] == "ok"
    assert by_id["2310.00001"]["is_zero_ref"] is True
    assert by_id["2310.00002"]["status"] == "failed"
    assert by_id["2310.00002"]["error_kind"] == "invalid_payload"
    assert by_id["2310.00003"]["status"] == "failed"
    assert by_id["2310.00003"]["error_kind"] == "invalid_payload"
    assert by_id["2310.00004"]["status"] == "ok"
    assert by_id["2310.00004"]["n_refs"] == 1
    assert by_id["2310.00005"]["status"] == "not_indexed"
    assert by_id["2310.00006"]["status"] == "failed"
    assert by_id["2310.00006"]["n_invalid_refs"] == 1
    assert by_id["2310.00007"]["status"] == "failed"
    assert by_id["2310.00007"]["error_kind"] == "http_500"

    assert cache_path_for(tmp_path, "2310.00001").exists()
    assert cache_path_for(tmp_path, "2310.00004").exists()
    for arxiv_id in ("2310.00002", "2310.00003", "2310.00005",
                     "2310.00006", "2310.00007"):
        assert not cache_path_for(tmp_path, arxiv_id).exists()

    assert json.loads(cache_path_for(tmp_path, "2310.00001")
                      .read_text(encoding="utf-8")) == []

    stats = summarize_s2_results(results)
    assert stats["n_input"] == 7
    assert stats["n_ok"] == 2
    assert stats["n_ok_fresh"] == 2
    assert stats["n_ok_from_cache"] == 0
    assert stats["n_attempted_fresh"] == 7
    assert stats["n_not_indexed"] == 1
    assert stats["n_failed"] == 4
    assert stats["n_api_errors"] == 1
    assert stats["n_processing_errors"] == 3
    assert stats["n_zero_refs"] == 1
    assert stats["n_refs_total"] == 1
    assert stats["n_refs_with_arxiv"] == 0
    assert stats["n_refs_without_arxiv"] == 1
    assert stats["success_rate_all_input"] == 2 / 7
    assert stats["success_rate_fresh"] == 2 / 7
    assert stats["avg_fetch_sample_count"] == 7
    assert stats["status_counts"] == {
        "ok": 2, "failed": 4, "not_indexed": 1,
    }


def test_batch_resume_skips_cache_hits_and_keeps_missing_elapsed(tmp_path, monkeypatch):
    responses = {
        "2310.00001": _FakeResponse(200, {"references": []}),
        "2310.00004": _FakeResponse(200, {"references": [{"paperId": "r1"}]}),
        "2310.00005": _FakeResponse(404, {}),
    }
    pacing_calls = _install_fake_http(monkeypatch, responses)
    papers = _papers(*responses)

    first, _ = run_s2_batch(papers, tmp_path, progress_every=100,
                            progress=lambda *_: None)
    assert len(pacing_calls) == 3

    second, _ = run_s2_batch(papers, tmp_path, progress_every=100,
                             progress=lambda *_: None)
    assert len(pacing_calls) == 4
    by_id = {row["arxiv_id"]: row for row in second}

    assert by_id["2310.00001"]["from_cache"] is True
    assert by_id["2310.00004"]["from_cache"] is True
    assert by_id["2310.00001"]["elapsed_s"] == ""
    assert by_id["2310.00004"]["elapsed_s"] == ""
    assert by_id["2310.00005"]["from_cache"] is False
    assert by_id["2310.00005"]["status"] == "not_indexed"

    stats = summarize_s2_results(second)
    assert stats["n_ok"] == 2
    assert stats["n_ok_from_cache"] == 2
    assert stats["n_ok_fresh"] == 0
    assert stats["n_cache_hits"] == 2
    assert stats["n_attempted_fresh"] == 1
    assert stats["success_rate_fresh"] == 0.0
    assert stats["n_refs_total"] == 1

    assert len(first) == len(second) == 3


def test_batch_recrawls_broken_cache_and_rejects_invalid_ids(tmp_path, monkeypatch):
    responses = {
        "2310.00004": _FakeResponse(200, {"references": [{"paperId": "r1"}]}),
    }
    _install_fake_http(monkeypatch, responses)
    cache_path = cache_path_for(tmp_path, "2310.00004")
    cache_path.write_text('["not-an-object"]', encoding="utf-8")

    results, n_invalid_ids = run_s2_batch(
        [{"arxiv_id": "2310.00004"}, {"arxiv_id": "not-an-id"}, {}],
        tmp_path,
        progress_every=100,
        progress=lambda *_: None,
    )

    assert n_invalid_ids == 2
    assert results[0]["from_cache"] is False
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "invalid_id"
    assert results[1]["elapsed_s"] == ""
    assert results[2]["status"] == "invalid_id"
    assert read_cached_records(cache_path)[0]["ref_s2_id"] == "r1"


class _Resp(_FakeResponse):
    headers = {}


def test_not_indexed_and_failed_do_not_write_cache(tmp_path, monkeypatch):
    from src.m1_crawling import s2_batch

    seq = iter([(None, "not_indexed", "HTTP 404 Not Found", "http_404"),
                (None, "failed", "HTTP 429 ...", "http_429")])
    monkeypatch.setattr(
        s2_batch, "fetch_s2_payload_with_status", lambda *a, **k: next(seq))
    results, _ = s2_batch.run_s2_batch(
        [{"arxiv_id": "2310.00001"}, {"arxiv_id": "2310.00002"}], tmp_path)
    assert [r["status"] for r in results] == ["not_indexed", "failed"]
    assert list(tmp_path.glob("*.json")) == []


def test_cache_resume_and_broken_cache_recrawl(tmp_path, monkeypatch):
    from src.m1_crawling import s2_batch

    (tmp_path / "2310-00001.json").write_text("[]", encoding="utf-8")
    (tmp_path / "2310-00002.json").write_text('{"x":1}', encoding="utf-8")
    monkeypatch.setattr(
        s2_batch, "fetch_s2_payload_with_status",
        lambda *a, **k: ({"references": []}, "ok", "", ""))
    results, _ = s2_batch.run_s2_batch(
        [{"arxiv_id": "2310.00001"}, {"arxiv_id": "2310.00002"}], tmp_path)
    assert results[0]["from_cache"] is True
    assert results[1]["from_cache"] is False


def test_summary_does_not_count_not_indexed_as_api_error():
    rows = [
        {"status": "not_indexed", "error_kind": "http_404",
         "from_cache": False},
        {"status": "failed", "error_kind": "http_429", "from_cache": False},
        {"status": "failed", "error_kind": "request_rejected",
         "from_cache": False},
    ]
    stats = summarize_s2_results(rows)
    assert stats["n_api_errors"] == 2
    assert stats["n_processing_errors"] == 0


def test_summary_counts_http_requests_retries_and_429():
    rows = [
        {"status": "ok", "from_cache": False, "n_http_requests": 3,
         "n_http_retries": 2, "n_http_429": 2},
        {"status": "ok", "from_cache": True, "n_http_requests": 0,
         "n_http_retries": 0, "n_http_429": 0},
    ]
    stats = summarize_s2_results(rows)
    assert stats["n_http_requests"] == 3
    assert stats["n_http_retries"] == 2
    assert stats["n_http_429"] == 2
    assert stats["retry_rate"] == pytest.approx(2 / 3)


def test_disk_peak_sampler_records_growth(tmp_path):
    from src.m1_crawling.s2_batch import DiskPeakSampler

    sampler = DiskPeakSampler(tmp_path, interval_sec=0.01).start()
    (tmp_path / "2310-00001.json").write_text("x" * 1000, encoding="utf-8")
    time.sleep(0.05)
    sampler.stop()
    result = sampler.result()
    assert result["peak_disk_bytes"] >= 1000
    assert result["disk_sample_count"] >= 2
    assert result["disk_sample_interval_sec"] == 0.01


def test_each_retry_attempt_is_paced(monkeypatch):
    from src.common import rate_limit

    seq = iter([_Resp(429, {}), _Resp(429, {}),
                _Resp(200, {"references": []})])
    paced = []
    monkeypatch.setattr(rate_limit.requests, "request", lambda *a, **k: next(seq))
    monkeypatch.setattr(rate_limit.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(s2, "_cooldown_until", 0.0)
    monkeypatch.setattr(
        s2, "_pace_s2_request", lambda has_key: paced.append(has_key))

    payload, status, _, _ = s2.fetch_s2_payload_with_status("2310.12345")
    assert payload == {"references": []}
    assert status == "ok"
    assert len(paced) == 3


def test_s2_fetch_counters_report_retries_and_429(monkeypatch):
    from src.common import rate_limit

    s2.reset_request_stats()
    seq = iter([_Resp(429, {}), _Resp(429, {}),
                _Resp(200, {"references": []})])
    monkeypatch.setattr(rate_limit.requests, "request",
                        lambda *a, **k: next(seq))
    monkeypatch.setattr(rate_limit.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(s2, "_cooldown_until", 0.0)
    monkeypatch.setattr(s2, "_pace_s2_request", lambda has_key: None)

    payload, status, _, _ = s2.fetch_s2_payload_with_status("2310.12345")
    assert payload == {"references": []}
    assert status == "ok"
    stats = s2.request_stats()
    assert stats["http_requests"] == 3
    assert stats["http_retries"] == 2
    assert stats["http_429"] == 2


def test_429_after_retries_sets_cooldown(monkeypatch):
    monkeypatch.setattr(s2, "request_with_retry", lambda *a, **k: _Resp(429, {}))
    monkeypatch.setattr(s2, "_cooldown_until", 0.0)
    monkeypatch.setattr(s2, "_pace_s2_request", lambda has_key: None)

    payload, status, _, error_kind = s2.fetch_s2_payload_with_status(
        "2310.12345")
    assert payload is None
    assert status == "failed"
    assert error_kind == "http_429"
    assert s2._cooldown_until > time.monotonic()


def test_cache_write_failure_is_failed_not_ok(tmp_path, monkeypatch):
    from src.m1_crawling import s2_batch

    monkeypatch.setattr(
        s2_batch, "fetch_s2_payload_with_status",
        lambda *a, **k: ({"references": []}, "ok", "", ""))

    def _broken_write(path, records):
        raise OSError("disk full")

    monkeypatch.setattr(s2_batch, "_write_cached_records", _broken_write)
    results, _ = s2_batch.run_s2_batch(
        [{"arxiv_id": "2310.00001"}], tmp_path)
    assert results[0]["status"] == "failed"
    assert results[0]["error_kind"] == "processing"
    assert results[0]["is_api_error"] is False
    stats = summarize_s2_results(results)
    assert stats["n_api_errors"] == 0
    assert stats["n_processing_errors"] == 1


def test_find_empty_cache_ids_and_force_recrawl(tmp_path, monkeypatch):
    from src.m1_crawling import s2_batch

    (tmp_path / "2310-00001.json").write_text("[]", encoding="utf-8")
    (tmp_path / "2310-00002.json").write_text(
        '[{"ref_s2_id": "r1", "ref_arxiv_id": null}]', encoding="utf-8")
    papers = [{"arxiv_id": "2310.00001"}, {"arxiv_id": "2310.00002"}]

    assert find_empty_cache_ids(papers, tmp_path) == ["2310.00001"]

    calls = []

    def fake_fetch(arxiv_id, api_key=None):
        calls.append(arxiv_id)
        return {"references": [{"paperId": "r2"}]}, "ok", "", ""

    monkeypatch.setattr(s2_batch, "fetch_s2_payload_with_status", fake_fetch)
    results, _ = run_s2_batch(
        papers, tmp_path, force_recrawl_ids=["2310.00001"])
    assert calls == ["2310.00001"]
    assert results[0]["from_cache"] is False
    assert results[1]["from_cache"] is True
    assert read_cached_records(tmp_path / "2310-00001.json")[0][
        "ref_s2_id"] == "r2"
