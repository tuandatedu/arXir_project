"""Offline tests: references per batch, table build, table validation, end-to-end CLI."""
import io
import json
import tarfile

import pytest

from src.m1_crawling import batch_references as br
from src.m1_crawling import run_m1_all
from src.m1_crawling.build_tables import build_tables
from src.m1_crawling.validate_tables import validate_papers, validate_references, validate_tables

IDS = ["2603.15001", "2603.15002", "2603.15003", "2603.15004", "2603.15005"]


def make_batch(data_dir, index=0, ids=IDS, not_found=("2603.15005",)):
    name = f"batch_{index:05d}"
    records = [{"arxiv_id": i, "status": "not_found" if i in not_found else "ok"} for i in ids]
    papers = [{"arxiv_id": i, "title": f"Paper {i}", "authors": ["A B"],
               "submission_date": "2026-03-01", "revised_dates": [], "venue": None}
              for i in ids if i not in not_found]
    archive = data_dir / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        for member, rows in (("crawl_records.jsonl", records), ("papers.jsonl", papers)):
            data = "\n".join(json.dumps(r) for r in rows).encode()
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    (data_dir / f"{name}.json").write_text(json.dumps(
        {"batch": name, "ids": ids, "archive_bytes": archive.stat().st_size,
         "archive_sha256": "abc", "ok": 4, "failed": 0, "no_tex": 0, "not_found": 1}))
    return name


def s2_ref(title, arxiv=None, pid="p"):
    return {"title": title, "authors": [{"name": "X"}], "publicationDate": "2017-06-12",
            "year": 2017, "externalIds": {"ArXiv": arxiv} if arxiv else {}, "paperId": pid}


@pytest.fixture
def fake_s2(monkeypatch):
    calls = []

    def fetch(arxiv_id, api_key=None):
        calls.append(arxiv_id)
        if arxiv_id.endswith("002"):
            raise RuntimeError("HTTP 500 after retries")
        if arxiv_id.endswith("003"):
            return []  # not indexed / no references
        refs = [s2_ref("Attention", "1706.03762", "s1"), s2_ref("A book", None, "s2"),
                s2_ref("Attention again", "1706.03762", "s3"),   # duplicate arXiv ID
                s2_ref("Broken", "not an id", "s4")]             # malformed arXiv ID
        return refs

    monkeypatch.setattr(br, "fetch_s2_references", fetch)
    return calls


def test_references_statuses_resume_and_manifest_untouched(tmp_path, fake_s2):
    name = make_batch(tmp_path)
    before = json.loads((tmp_path / f"{name}.json").read_text())
    br.crawl_references(tmp_path)
    manifest = json.loads((tmp_path / f"{name}.json").read_text())
    assert manifest["ids"] == before["ids"] and manifest["archive_bytes"] == before["archive_bytes"]
    ref = manifest["references"]
    assert (ref["papers_ok"], ref["papers_empty"], ref["papers_error"], ref["papers_skipped"]) == (2, 1, 1, 1)
    assert sorted(p.name for p in (tmp_path / "reference_00000").glob("*.json")) == [
        "2603-15001.json", "2603-15002.json", "2603-15003.json", "2603-15004.json"]
    fake_s2.clear()
    br.crawl_references(tmp_path)          # only the failed paper is requested again
    assert fake_s2 == ["2603.15002"]
    fake_s2.clear()
    br.crawl_references(tmp_path, retry_empty=True)
    assert fake_s2 == ["2603.15002", "2603.15003"]


def test_build_keeps_only_valid_arxiv_refs_and_dedups(tmp_path, fake_s2):
    make_batch(tmp_path)
    br.crawl_references(tmp_path)
    report = build_tables(tmp_path)
    rows = [json.loads(l) for l in (tmp_path / "tables" / "references.jsonl").read_text().splitlines()]
    assert {(r["arxiv_id"], r["ref_arxiv_id"]) for r in rows} == {
        ("2603.15001", "1706.03762"), ("2603.15004", "1706.03762")}
    assert report["papers_rows"] == 4 and report["references_rows"] == 2
    stats = report["references"]
    assert stats["references_invalid_arxiv_id"] == 2        # one per OK paper, no crash
    assert stats["references_duplicates_removed"] == 2
    assert stats["papers_without_reference_data"] == ["2603.15002"]   # error paper listed


def test_validate_detects_problems():
    papers = [
        {"arxiv_id": "2603.15001v2", "title": "", "authors": "A B", "submission_date": "03/2026",
         "revised_dates": ["2026-01-01"], "venue": ""},
        {"arxiv_id": "2603.15002", "title": "ok", "authors": ["A"], "submission_date": "2026-03-01",
         "revised_dates": [], "venue": None},
        {"arxiv_id": "2603.15002", "title": "dup", "authors": ["A"], "submission_date": "2026-03-01",
         "revised_dates": [], "venue": None},
        {"arxiv_id": "2603.15003", "title": "x"},
    ]
    codes = {i["code"] for i in validate_papers(papers)}
    assert {"invalid_arxiv_id", "missing_title", "type", "bad_date", "empty_venue",
            "duplicate_arxiv_id", "columns"} <= codes
    good = {"arxiv_id": "2603.15002", "ref_arxiv_id": "1706.03762", "ref_title": "T",
            "ref_authors": ["A"], "ref_submission_date": "2017", "ref_s2_id": "s"}
    refs = [good, dict(good), {**good, "ref_arxiv_id": None}, {**good, "arxiv_id": "9999.00001"},
            {**good, "ref_authors": [], "ref_s2_id": "", "ref_submission_date": "June"}]
    codes = {i["code"] for i in validate_references(refs, {"2603.15002"})}
    assert {"duplicate_reference", "invalid_ref_arxiv_id", "orphan_reference",
            "missing_ref_authors", "missing_ref_s2_id", "bad_date"} <= codes


def test_end_to_end_cli_without_network(tmp_path, fake_s2):
    make_batch(tmp_path)
    code = run_m1_all.main(["--range", "5", "--data-dir", str(tmp_path), "--skip-crawl", "--no-report"])
    assert code == 0                                  # tables valid
    assert validate_tables(tmp_path / "tables", verbose=False)["ok"]
    summary = json.loads((tmp_path / "tables" / "m1_run_summary.json").read_text())
    assert summary["validation_ok"] and summary["build"]["papers_rows"] == 4
