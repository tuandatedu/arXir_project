"""Offline tests cho phần M1 mới: common helpers + S2 + tables + pipeline.

Chạy: python -m pytest -q tests/test_m1_pipeline.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.ids import (
    folder_name_for_arxiv_id,
    normalize_arxiv_id,
    parse_version_suffix,
    versioned_id,
)
from src.common.io import load_assigned_ids, read_json, read_jsonl, write_jsonl
from src.m1_crawling.discover import PaperMeta
from src.m1_crawling.semantic_scholar import (
    extract_arxiv_id_from_external_ids,
    fetch_s2_references,
    s2_ref_to_local_record,
)
from src.m1_crawling.tables import (
    paper_meta_to_row,
    s2_records_to_reference_rows,
    validate_m1_tables,
    write_m1_tables,
)


def test_normalize_arxiv_id_variants():
    assert normalize_arxiv_id("2310.12345v4") == "2310.12345"
    assert normalize_arxiv_id("arXiv:2310.12345") == "2310.12345"
    assert normalize_arxiv_id("https://arxiv.org/abs/hep-th/9901001v2") == "hep-th/9901001"
    assert normalize_arxiv_id("hep-th/9901001") == "hep-th/9901001"
    assert parse_version_suffix("2310.12345v4") == 4
    assert parse_version_suffix("2310.12345") is None
    assert folder_name_for_arxiv_id("2310.12345") == "2310-12345"
    assert folder_name_for_arxiv_id("hep-th/9901001") == "hep-th_9901001"
    assert versioned_id("2310.12345", 2) == "2310.12345v2"
    with pytest.raises(ValueError):
        normalize_arxiv_id("not-an-id")


def test_load_assigned_ids(tmp_path):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(
        "# comment\n\n2310.12345v1\n2310.12345\nhep-th/9901001\n", encoding="utf-8")
    assert load_assigned_ids(ids_file) == ["2310.12345", "hep-th/9901001"]


def test_extract_arxiv_id_from_external_ids():
    assert extract_arxiv_id_from_external_ids({"ArXiv": "2310.12345"}) == "2310.12345"
    assert extract_arxiv_id_from_external_ids({"ArXiv": "hep-th/9901001v3"}) == "hep-th/9901001"
    assert extract_arxiv_id_from_external_ids({"DOI": "10.1/xyz"}) is None
    assert extract_arxiv_id_from_external_ids(None) is None


def test_s2_ref_to_local_record_shapes():
    raw = {
        "paperId": "abc123",
        "title": "  A Reference  ",
        "authors": [{"authorId": "1", "name": "Alice"}, {"authorId": "2", "name": "Bob"}, {}],
        "year": 2017,
        "publicationDate": "2017-05-11",
        "venue": "NeurIPS",
        "externalIds": {"ArXiv": "1706.03762", "DOI": "x"},
    }
    record = s2_ref_to_local_record("2310.12345", raw)
    assert record["arxiv_id"] == "2310.12345"
    assert record["ref_title"] == "A Reference"
    assert record["ref_authors"] == ["Alice", "Bob"]
    assert record["ref_submission_date"] == "2017-05-11"
    assert record["ref_arxiv_id"] == "1706.03762"
    assert record["ref_s2_id"] == "abc123"
    assert record["venue"] == "NeurIPS"
    assert record["year"] == 2017

    bare = s2_ref_to_local_record("2310.12345", {"paperId": "z", "year": 2020})
    assert bare["ref_arxiv_id"] is None
    assert bare["ref_submission_date"] == "2020"
    assert bare["ref_title"] == ""


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.closed = False

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


def test_fetch_s2_references_handles_404_and_parses(monkeypatch):
    from src.m1_crawling import semantic_scholar as s2

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        if "2310.99999" in url:
            return _FakeResponse(404, {})
        return _FakeResponse(200, {"references": [
            {"paperId": "r1", "title": "T1", "authors": [],
             "externalIds": {"ArXiv": "2001.00001"}},
            "not-an-object",
        ]})

    monkeypatch.setattr(s2, "request_with_retry", fake_request)
    monkeypatch.setattr(s2, "S2_MIN_DELAY_SEC", 0.0)
    monkeypatch.setattr(s2, "S2_MIN_DELAY_UNAUTH_SEC", 0.0)

    missing = fetch_s2_references("2310.99999")
    assert missing == []
    refs = fetch_s2_references("2310.12345")
    assert len(refs) == 1 and refs[0]["paperId"] == "r1"
    assert len(calls) == 2


def test_s2_records_to_reference_rows_filters_non_arxiv():
    records = [
        {"arxiv_id": "2310.12345", "ref_title": "A", "ref_authors": ["X"],
         "ref_submission_date": "2020-01-01", "ref_arxiv_id": "2001.00001",
         "ref_s2_id": "s1"},
        {"arxiv_id": "2310.12345", "ref_title": "B", "ref_authors": ["Y"],
         "ref_submission_date": "", "ref_arxiv_id": None, "ref_s2_id": "s2",
         "year": 2019},
        {"arxiv_id": "2310.12345", "ref_title": "C", "ref_authors": ["Z"],
         "ref_submission_date": "2018", "ref_arxiv_id": "hep-th/9901001",
         "ref_s2_id": "s3"},
    ]
    rows = s2_records_to_reference_rows("2310.12345", records)
    assert [r.ref_arxiv_id for r in rows] == ["2001.00001", "hep-th/9901001"]


def test_validate_m1_tables_flags_issues():
    meta = PaperMeta(arxiv_id="2310.12345", title="Hello",
                     authors=["Alice"], submission_date="2023-10-02")
    good = paper_meta_to_row(meta)
    bad_missing = paper_meta_to_row(PaperMeta(
        arxiv_id="2310.12346", title="", authors=[], submission_date=""))

    ref_good = s2_records_to_reference_rows("2310.12345", [{
        "ref_title": "T", "ref_authors": ["A"], "ref_submission_date": "2020",
        "ref_arxiv_id": "2001.00001", "ref_s2_id": "s1"}])[0]
    report = validate_m1_tables([good, good, bad_missing], [ref_good, ref_good])
    assert not report["ok"]
    assert any(i["table"] == "papers" and i["problem"].startswith("duplicate")
               for i in report["issues"])
    assert any(i["field"] == "title" for i in report["issues"]
               if i["table"] == "papers")
    assert any(i["field"] == "authors" for i in report["issues"]
               if i["table"] == "papers")
    assert any(i["field"] == "arxiv_id" and i["table"] == "references"
               and i["problem"].startswith("duplicate")
               for i in report["issues"])

    report2 = validate_m1_tables(
        [paper_meta_to_row(PaperMeta(arxiv_id="2310.12345", title="Hello",
                                     authors=["Alice"],
                                     submission_date="2023-10-02"))],
        [ref_good])
    assert report2["ok"]

    typed = dict(arxiv_id="2310.12345", title="Hello", authors=["Alice"],
                 submission_date="2023-10-02", revised_dates=["not-a-list-str"]
                 if False else ["2023-10-03"], venue=None)
    wrong = validate_m1_tables([dict(typed, authors="Alice")], [])
    assert any(i["field"] == "authors" and "expected list" in i["problem"]
               for i in wrong["issues"])


def test_write_m1_tables_and_read_back(tmp_path, monkeypatch):
    from src.common import config
    monkeypatch.setattr(config, "TABLES_DIR", tmp_path)
    meta = PaperMeta(arxiv_id="2310.12345", title="Hello",
                     authors=["Alice"], submission_date="2023-10-02")
    row = paper_meta_to_row(meta)
    ref = s2_records_to_reference_rows("2310.12345", [{
        "ref_title": "T", "ref_authors": ["A"], "ref_submission_date": "2020",
        "ref_arxiv_id": "2001.00001", "ref_s2_id": "s1"}])[0]
    write_m1_tables([row], [ref])
    papers = read_json(tmp_path / "papers.json")
    references = read_json(tmp_path / "references.json")
    assert papers[0]["arxiv_id"] == "2310.12345"
    assert references[0]["ref_arxiv_id"] == "2001.00001"


def test_run_milestone1_end_to_end_mocked(tmp_path, monkeypatch):
    """Nối pipeline: assigned ids → crawl (mock network) → tables + metrics."""
    from src.common import config
    from src.m1_crawling import pipeline
    from src.m1_crawling.semantic_scholar import s2_ref_to_local_record

    monkeypatch.setattr(config, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(config, "TABLES_DIR", tmp_path / "tables")
    monkeypatch.setattr(config, "ASSIGNED_IDS_FILE", tmp_path / "none.txt")

    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2310.12345\n", encoding="utf-8")

    meta = PaperMeta(arxiv_id="2310.12345", title="Hello",
                     authors=["Alice"], submission_date="2023-10-02",
                     latest_version=2)

    def fake_crawl(arxiv_id, *, s2_api_key=None):
        from src.m1_crawling.corpus import (
            publication_dir, save_paper_meta, save_s2_references,
            save_version_sources, version_source_dir,
        )
        from src.common.io import write_json

        save_paper_meta(arxiv_id, meta)
        for version in (1, 2):
            sources = version_source_dir(arxiv_id, version)
            sources.mkdir(parents=True, exist_ok=True)
            tex = sources / "main.tex"
            tex.write_text("\\documentclass{article}\n", encoding="utf-8")
            if version == 1:
                save_version_sources(arxiv_id, version, [], empty=False)
            else:
                save_version_sources(arxiv_id, version, [], empty=True,
                                     reason="pdf-only")
            write_json(publication_dir(arxiv_id) / f"v{version}" / "metadata.json", {
                "version": version,
                "status": "ok" if version == 1 else "no_tex",
                "reason": "" if version == 1 else "pdf-only",
                "archive_bytes": 1000,
                "n_files": 1 if version == 1 else 0,
                "extracted_bytes": 50 if version == 1 else 0,
            })
        records = [s2_ref_to_local_record(arxiv_id, {
            "paperId": "r1", "title": "Ref", "authors": [{"name": "Bob"}],
            "publicationDate": "2020-01-02", "externalIds": {"ArXiv": "2001.00001"}})]
        save_s2_references(arxiv_id, records)
        return {"arxiv_id": arxiv_id, "status": "ok", "meta": meta,
                "n_versions": 2, "n_tex": 1, "n_refs": 1, "n_refs_with_arxiv": 1,
                "bytes_archive": 1000, "bytes_extracted": 50, "errors": []}

    monkeypatch.setattr(pipeline, "crawl_one_publication", fake_crawl)
    monkeypatch.setattr(pipeline, "track_run",
                        lambda name: _fake_track_run(tmp_path / "tables"))

    papers, references = pipeline.run_milestone1(ids_file)
    assert len(papers) == 1 and papers[0].arxiv_id == "2310.12345"
    assert len(references) == 1 and references[0].ref_arxiv_id == "2001.00001"

    assert (tmp_path / "tables" / "papers.json").exists()
    assert (tmp_path / "tables" / "references.json").exists()
    metrics = json.loads((tmp_path / "tables" / "metrics_m1.json")
                         .read_text(encoding="utf-8"))
    assert metrics["n_ok"] == 1
    assert metrics["n_references"] == 1
    assert metrics["validation_ok"] is True
    assert metrics["corpus_n_empty_versions"] == 1
    # references_s2.json giữ đủ ref (kể cả không arXiv) — ở đây 1 ref có arXiv.
    refs_local = read_jsonl(tmp_path / "working" / "2310-12345"
                            / "references_s2.json")
    assert len(refs_local) == 1


class _fake_track_run:
    def __init__(self, tables_dir):
        self.tables_dir = tables_dir

    def __enter__(self):
        return {}

    def __exit__(self, *exc):
        return False
