"""Offline tests for wall-clock ledger, no arXiv network access."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from src.m1_crawling.runtime_tracking import (
    HISTORY_FIELDS, checkpoint_state, read_runtime_history, record_runtime,
    summarize_runtime,
)
from src.m1_crawling.export_reports import export_reports


def _event(root: Path, mode: str, seconds: float, before=None, after=None, code=0):
    return record_runtime(
        root, mode=mode, range_id=5, batch_size=50, batches_requested=1,
        elapsed_seconds=seconds, exit_code=code,
        started_at_utc="2026-10-26T03:00:00+00:00",
        before=before or {}, after=after or {},
    )


def test_runtime_history_cumulative_and_idempotent(tmp_path):
    a = _event(tmp_path, "fast", 440.125, after={"batch_00000.json": (1, 1)}, code=2)
    b = _event(tmp_path, "recovery", 220.5,
               before={"batch_00000.json": (1, 1)},
               after={"batch_00000.json": (2, 2)})
    c = _event(tmp_path, "recovery", 30.25)
    assert a["result"] == "partial"
    assert b["updated_checkpoints"] == 1
    assert a["run_id"] != b["run_id"]
    rows = read_runtime_history(tmp_path)
    assert len(rows) == 3
    summary = summarize_runtime(rows, total_records=50)
    assert summary["fast_crawl_seconds"] == 440.125
    assert summary["recovery_seconds"] == 250.75
    assert summary["total_runtime_seconds"] == 690.875
    assert summary["recovery_attempts"] == 2
    assert summary["average_seconds_per_id"] == 13.818
    assert len(read_runtime_history(tmp_path)) == 3  # reading never appends


def test_history_missing(tmp_path):
    assert read_runtime_history(tmp_path) == []
    assert summarize_runtime([], 50)["total_runtime_seconds"] == 0
    assert summarize_runtime([], 0)["average_seconds_per_id"] is None


def test_history_fails_on_duplicate_run_ids(tmp_path):
    _event(tmp_path, "fast", 1)
    rows = read_runtime_history(tmp_path)
    path = tmp_path / "runtime_history.csv"
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writerow(rows[0])
    import pytest
    with pytest.raises(ValueError, match="Duplicate"):
        read_runtime_history(tmp_path)


def test_export_integration_with_existing_archive(tmp_path, monkeypatch):
    """Use existing mocked crawler; exporting twice cannot double-count."""
    from src.m1_crawling import run_arxiv_only as main
    import io
    import tarfile

    class FakeResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class FakeHTTP:
        request_count = 0
        retry_count = 0
        def get(self, url, *, params=None, stream=False):
            return FakeResponse(b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2604.00535v1</id><title>A</title>
<published>2026-04-01T10:00:00Z</published>
<updated>2026-04-01T10:00:00Z</updated>
<author><name>Test</name></author></entry><entry>
<id>http://arxiv.org/abs/2604.00536v1</id><title>B</title>
<published>2026-04-01T10:00:00Z</published>
<updated>2026-04-01T10:00:00Z</updated>
<author><name>Test</name></author></entry></feed>''')

    def make_tar(path, members):
        with tarfile.open(path, "w:gz") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    def fake_download(pid, ver, dest, http=None):
        make_tar(dest, {"main.tex": b"\\documentclass{article}"})
        return dest

    monkeypatch.setattr(main, "download_source_archive", fake_download)
    backup = tmp_path / "backup"
    main._run_batch(["2604.00535", "2604.00536"], "batch_00000",
                    tmp_path / "scratch", backup, FakeHTTP(), False, False, False)
    _event(backup, "fast", 440.0)
    _event(backup, "recovery", 220.0)
    first = export_reports(backup)
    second = export_reports(backup)
    assert first["total_runtime_seconds"] == second["total_runtime_seconds"] == 660
    assert first["fast_crawl_seconds"] == 440
    assert first["recovery_seconds"] == 220
    assert first["recovery_attempts"] == 1
    assert first["average_seconds_per_id"] == 330
    assert (backup / "reports" / "runtime_history.csv").exists()
    assert len(read_runtime_history(backup)) == 2
    text = (backup / "reports" / "README_BAO_CAO.txt").read_text(encoding="utf-8")
    assert "660.0 giây" in text
