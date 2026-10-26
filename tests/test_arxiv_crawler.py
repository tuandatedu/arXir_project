"""Offline tests: run `python -m pytest -q tests/test_arxiv_crawler.py`."""
from __future__ import annotations

import gzip
import io
from pathlib import Path
import tarfile
import zipfile

import pytest

from src.m1_crawling.assigned_ranges import assigned_ids, range_ids, RANGES
from src.m1_crawling.discover import _parse_feed, list_versions, PaperMeta, fetch_papers_by_ids
from src.m1_crawling.download import (
    detect_archive_kind, extract_tex_and_bib, source_url,
    download_source_archive,
)
from src.m1_crawling.arxiv_http import ArxivHTTP
from src.m1_crawling.run_arxiv_only import build_batches, _run_batch, _existing_manifest

FEED = b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry><id>http://arxiv.org/abs/2604.00535v3</id><title> Test   paper </title>
  <published>2026-04-01T10:00:00Z</published><updated>2026-04-04T10:00:00Z</updated>
  <summary> Description </summary><author><name>A. Person</name></author>
  <arxiv:journal_ref>Journal Name</arxiv:journal_ref></entry>
  <entry><id>http://arxiv.org/abs/2604.00536v1</id><title> Second </title>
  <published>2026-04-01T11:00:00Z</published><updated>2026-04-01T11:00:00Z</updated>
  <author><name>B. Person</name></author></entry>
</feed>'''


def make_tar(path: Path, members: dict[str, bytes]):
    with tarfile.open(path, "w:gz") as t:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            t.addfile(info, io.BytesIO(content))


def test_assigned_ranges_are_valid_and_disjoint():
    ids = assigned_ids()

    assert len(ids) > 0
    assert len(ids) == len(set(ids))


def test_parse_metadata_and_versions():
    papers = _parse_feed(FEED)
    assert set(papers) == {"2604.00535", "2604.00536"}
    assert papers["2604.00535"].latest_version == 3
    assert list_versions(papers["2604.00535"]) == [1, 2, 3]
    assert papers["2604.00535"].submission_date == "2026-04-01"
    assert papers["2604.00535"].venue == "Journal Name"
    assert papers["2604.00536"].revised_dates == []


def test_arxiv_urls_and_pacing_constraints():
    assert source_url("2604.00535", 2) == "https://export.arxiv.org/src/2604.00535v2"
    with pytest.raises(ValueError):
        source_url("../../secret", 1)
    with pytest.raises(ValueError):
        ArxivHTTP(delay=1)


def test_extract_only_tex_bib_keep_bytes_and_paths(tmp_path):
    archive = tmp_path / "s.bin"
    tex = b"\\begin{figure}\\includegraphics{a.png}\\end{figure}\n"
    make_tar(archive, {"main.tex": tex, "references.bib": b"@article{x}\n",
                       "sections/intro.tex": b"Hello", "images/a.png": b"\x89PNG"})
    assert detect_archive_kind(archive) == "targz"
    files = extract_tex_and_bib(archive, tmp_path / "out")
    assert sorted(p.name for p in files) == ["intro.tex", "main.tex", "references.bib"]
    assert (tmp_path / "out" / "main.tex").read_bytes() == tex
    assert not (tmp_path / "out" / "images" / "a.png").exists()


def test_archive_path_traversal_and_symlink_not_extracted(tmp_path):
    archive = tmp_path / "s.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        for name in ("../../evil.tex", "/tmp/evil.tex", "legit.tex"):
            content = b"hello"
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        link = tarfile.TarInfo("link.tex")
        link.type = tarfile.SYMTYPE
        link.linkname = "../evil.tex"
        tf.addfile(link)
    files = extract_tex_and_bib(archive, tmp_path / "out")
    assert len(files) == 1
    assert files[0].name == "legit.tex"
    assert not (tmp_path / "evil.tex").exists()


def test_zip_and_gzip_and_pdf(tmp_path):
    zipped = tmp_path / "archive"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("sub/one.tex", "\\documentclass{article}")
        z.writestr("one.jpg", "xxx")
    assert detect_archive_kind(zipped) == "zip"
    assert len(extract_tex_and_bib(zipped, tmp_path / "zip_out")) == 1
    plain_gz = tmp_path / "single.gz"
    with gzip.open(plain_gz, "wb") as f:
        f.write(b"\\documentclass{article}\n")
    assert detect_archive_kind(plain_gz) == "gz"
    assert len(extract_tex_and_bib(plain_gz, tmp_path / "gz_out")) == 1
    pdf = tmp_path / "pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    assert detect_archive_kind(pdf) == "pdf"
    assert extract_tex_and_bib(pdf, tmp_path / "pdf_out") == []


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


class FakeHTTP:
    def __init__(self):
        self.calls = 0
        self.request_count = 0
        self.retry_count = 0
    def get(self, url, *, params=None, stream=False):
        self.calls += 1
        self.request_count += 1
        return FakeResponse(FEED)


def test_batch_metadata_one_request_and_not_found():
    fake = FakeHTTP()
    found = fetch_papers_by_ids(["2604.00535", "2604.00536", "2604.99999"], fake)
    assert fake.calls == 1
    assert len(found) == 2


def test_batch_resume_mock_http(monkeypatch, tmp_path):
    from src.m1_crawling import run_arxiv_only as main
    http = FakeHTTP()
    # Avoid external source calls entirely: emulate a versioned archive returned.
    def fake_download(pid, ver, dest, http=None):
        make_tar(dest, {"main.tex": f"\\documentclass{{article}} % {pid} v{ver}".encode()})
        return dest
    monkeypatch.setattr(main, "download_source_archive", fake_download)
    ids = ["2604.00535", "2604.00536"]
    backup = tmp_path / "backup"
    output = tmp_path / "scratch"
    m1 = _run_batch(ids, "batch_00000", output, backup, http, False, False, False)
    assert m1["ok"] == 2
    assert m1["failed"] == 0
    assert m1["archive_bytes"] > 0
    assert not (output / "batch_00000").exists()
    calls = http.calls
    m2 = _run_batch(ids, "batch_00000", output, backup, http, False, False, False)
    assert http.calls == calls
    assert m2["ok"] == 2
    assert _existing_manifest(backup, "batch_00000", ids, True) is not None


def test_summarize_backups(monkeypatch, tmp_path):
    from src.m1_crawling import run_arxiv_only as main
    from src.m1_crawling.summarize_backups import summarize
    def fake_download(pid, ver, dest, http=None):
        make_tar(dest, {"main.tex": b"\\documentclass{article}"})
        return dest
    monkeypatch.setattr(main, "download_source_archive", fake_download)
    _run_batch(["2604.00535", "2604.00536"], "batch_00000",
               tmp_path / "scratch", tmp_path / "backups", FakeHTTP(), False, False, False)
    summary = summarize(tmp_path / "backups", tmp_path / "summary")
    assert summary["batch_count"] == 1
    assert summary["metadata_rows"] == 2
    assert summary["crawl_record_rows"] == 2
    assert summary["failed"] == 0


def test_retry_failed_keeps_successful_other_papers(monkeypatch, tmp_path):
    from src.m1_crawling import run_arxiv_only as main
    from src.m1_crawling.arxiv_http import ArxivHTTPError
    calls = []
    fail_once = {"flag": True}

    def flaky(pid, ver, dest, http=None):
        calls.append((pid, ver))
        if pid == "2604.00535" and ver == 1 and fail_once["flag"]:
            fail_once["flag"] = False
            raise ArxivHTTPError("Transient HTTP 503", 503)
        make_tar(dest, {"main.tex": b"\\documentclass{article}"})
        return dest

    monkeypatch.setattr(main, "download_source_archive", flaky)
    ids = ["2604.00535", "2604.00536"]
    a = _run_batch(ids, "batch_00000", tmp_path / "scratch", tmp_path / "backup",
                   FakeHTTP(), False, False, False)
    assert a["failed"] == 1
    success_calls = calls.count(("2604.00536", 1))
    assert success_calls == 1
    b = _run_batch(ids, "batch_00000", tmp_path / "scratch", tmp_path / "backup",
                   FakeHTTP(), False, True, False)
    assert b["failed"] == 0
    assert calls.count(("2604.00536", 1)) == success_calls


def test_recovery_only_retries_failed_version_and_exports(monkeypatch, tmp_path):
    from src.m1_crawling import run_arxiv_only as main
    from src.m1_crawling.arxiv_http import ArxivHTTPError
    from src.m1_crawling.export_reports import export_reports
    import csv
    import json

    calls = []
    failed = {"first": True}

    def flaky(pid, ver, dest, http=None):
        calls.append((pid, ver))
        if (pid, ver) == ("2604.00535", 2) and failed["first"]:
            failed["first"] = False
            raise ArxivHTTPError("connection interrupted")
        make_tar(dest, {"main.tex": f"\\documentclass{{article}} v{ver}".encode()})
        return dest

    monkeypatch.setattr(main, "download_source_archive", flaky)
    ids = ["2604.00535", "2604.00536"]
    backup = tmp_path / "backup"
    scratch = tmp_path / "scratch"
    a = _run_batch(ids, "batch_00000", scratch, backup, FakeHTTP(), False, False, False)
    assert a["failed"] == 1
    assert calls.count(("2604.00535", 1)) == 1
    assert calls.count(("2604.00535", 3)) == 1
    assert calls.count(("2604.00536", 1)) == 1
    before_summary = export_reports(backup, backup / "report_before")
    assert before_summary["failed_version_rows"] == 1
    with (backup / "report_before" / "failed_versions.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        missing = list(csv.DictReader(f))
    assert missing[0]["versioned_id"] == "2604.00535v2"

    # A second run must retry only v2 of the failing paper.
    http = FakeHTTP()
    b = _run_batch(ids, "batch_00000", scratch, backup, http, False, True, False)
    assert b["failed"] == 0 and b["ok"] == 2
    assert calls.count(("2604.00535", 1)) == 1
    assert calls.count(("2604.00535", 2)) == 2
    assert calls.count(("2604.00535", 3)) == 1
    assert calls.count(("2604.00536", 1)) == 1
    assert http.calls == 0  # cached metadata; no redundant API calls

    summary = export_reports(backup)
    assert summary["ok"] == 2
    assert summary["failed_version_rows"] == 0
    report = backup / "reports"
    with (report / "papers.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["arxiv_id"] == "2604.00535"
    assert json.loads(rows[0]["authors"]) == ["A. Person"]
    with (report / "crawl_records.csv").open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    assert len(json.loads(records[0]["versions"])) == 3
