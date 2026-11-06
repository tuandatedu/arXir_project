"""Multi-range integration: repeated batch names, input association, and resume."""

import hashlib
import io
import json
import tarfile

import pytest

from src.common.ids import folder_name_for_arxiv_id
from src.m2_parsing.batch_pipeline import run_checkpoint_batches
from src.m2_parsing.range_inputs import (create_input_layout, parse_range_selection,
                                        run_selected_ranges, selection_output_dir)
from src.m2_parsing.run_m2 import main, parse_args


def make_range(root, number, arxiv_id=None):
    arxiv_id = arxiv_id or f"2310.{number:05d}"
    directory = root / f"range_{number}" / "sources"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "batch_00000.tar.gz"
    source = (r"\documentclass{article}\begin{document}\section{Intro}"
              r"A result. See \cite{k}. \begin{thebibliography}{1}"
              r"\bibitem{k} Jane Doe. A Study. 2020.\end{thebibliography}\end{document}")
    payload = source.encode()
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo(f"working/{folder_name_for_arxiv_id(arxiv_id)}/v1/sources/main.tex")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    manifest = {"ids": [arxiv_id], "archive_bytes": archive.stat().st_size,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    archive.with_name("batch_00000.json").write_text(json.dumps(manifest), encoding="utf-8")
    return arxiv_id


def add_references(root, number, arxiv_id, jsonl=False, nested=False):
    directory = root / f"range_{number}" / "references"
    if nested:
        directory /= "tables"
    directory.mkdir(parents=True, exist_ok=True)
    tables = {"papers": [{"arxiv_id": arxiv_id, "title": "Paper"}],
              "references": [{"arxiv_id": arxiv_id, "ref_arxiv_id": "hep-th/9901001",
                              "ref_s2_id": "s2", "ref_title": "A Study"}]}
    for name, rows in tables.items():
        content = "\n".join(json.dumps(row) for row in rows) if jsonl else json.dumps(rows)
        (directory / f"{name}.{'jsonl' if jsonl else 'json'}").write_text(content, encoding="utf-8")


@pytest.mark.parametrize("selection, expected", [
    ("1", [1]), ("3,1,3", [1, 3]), (["1", "5"], [1, 5]),
    ("range_2 range_4", [2, 4]), ("all", [1, 2, 3, 4, 5]),
])
def test_parse_selection(selection, expected):
    assert parse_range_selection(selection) == expected


@pytest.mark.parametrize("selection", ["", "0", "6", "1,all", "1-5", "hello"])
def test_invalid_selection(selection):
    with pytest.raises(ValueError):
        parse_range_selection(selection)


def test_create_empty_layout_is_idempotent(tmp_path):
    create_input_layout(tmp_path)
    create_input_layout(tmp_path)
    assert len(list(tmp_path.glob("range_*/*"))) == 10
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_five_ranges_parallel_and_resume(tmp_path):
    root = tmp_path / "input"
    create_input_layout(root)
    for number in range(1, 6):
        arxiv_id = make_range(root, number)
        add_references(root, number, arxiv_id, jsonl=number % 2 == 0, nested=number == 5)
    tables = tmp_path / "tables"
    metrics = run_selected_ranges(root, [1, 2, 3, 4, 5], tmp_path / "working", tables,
                                  workers=2, require_references=True)
    assert metrics["n_publications"] == metrics["batch_count"] == 5
    assert metrics["n_versions_parsed"] == 5
    assert metrics["n_versions_failed"] == metrics["n_versions_partial"] == 0
    assert len(list((tables / "batches").glob("range_*/batch_00000/complete.json"))) == 5
    originals = {name: (tables / f"{name}.jsonl").read_bytes()
                 for name in ("elements", "hierarchy", "bibtex")}
    for content in originals.values():
        assert {json.loads(line)["arxiv_id"] for line in content.splitlines()} == {
            f"2310.{number:05d}" for number in range(1, 6)}
    for name in ("papers", "references"):
        rows = [json.loads(line) for line in (tables / "m1" / f"{name}.jsonl").read_text().splitlines()]
        assert {row["arxiv_id"] for row in rows} == {f"2310.{n:05d}" for n in range(1, 6)}
    resumed = run_selected_ranges(root, [1, 2, 3, 4, 5], tmp_path / "working", tables,
                                  workers=2, resume=True)
    assert resumed["reused_batches"] == 5
    assert all((tables / f"{name}.jsonl").read_bytes() == data for name, data in originals.items())


def test_interactive_subset_and_missing_references(tmp_path, monkeypatch, caplog):
    root = tmp_path / "input"
    for number in (1, 3):
        make_range(root, number)
    answers = iter(["6", "3,1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    output_root = tmp_path / "output"
    assert main(["--select-ranges", "--input-root", str(root), "--output-root", str(output_root),
                 "--working-dir", str(tmp_path / "working")]) == 0
    tables = selection_output_dir(output_root, [1, 3])
    report = json.loads((tables / "input_report.json").read_text(encoding="utf-8"))
    assert report["selected_ranges"] == [1, 3]
    assert report["ranges"]["range_1"]["reference_status"] == "missing"
    assert "chưa có references" in caplog.text
    assert (tables / "m1" / "references.jsonl").read_text() == ""
    assert json.loads((tables / "metrics_m2.json").read_text())["n_publications"] == 2


@pytest.mark.parametrize("problem", ["overlap", "missing_source", "wrong_reference", "missing_reference", "manifest"])
def test_bad_input_does_not_truncate_output(tmp_path, problem):
    root, tables = tmp_path / "input", tmp_path / "tables"
    arxiv_id = make_range(root, 1)
    make_range(root, 2, arxiv_id if problem == "overlap" else None)
    add_references(root, 1, "2310.99999" if problem == "wrong_reference" else arxiv_id)
    if problem == "manifest":
        (root / "range_2" / "sources" / "batch_00000.json").unlink()
    tables.mkdir()
    sentinel = tables / "elements.jsonl"
    sentinel.write_text("previous output", encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        run_selected_ranges(root, [1, 3] if problem == "missing_source" else [1, 2],
                            tmp_path / "working", tables,
                            require_references=problem == "missing_reference")
    assert sentinel.read_text() == "previous output"
    assert not (tables / "batches").exists()


def test_legacy_single_batch_directory(tmp_path):
    root = tmp_path / "input"
    make_range(root, 1)
    tables = tmp_path / "tables"
    metrics = run_checkpoint_batches(root / "range_1" / "sources", tmp_path / "working", tables)
    assert metrics["n_publications"] == 1
    assert (tables / "batches" / "batch_00000" / "complete.json").is_file()


@pytest.mark.parametrize("problem", ["ambiguous", "duplicate", "invalid_id", "raw_api", "invalid_manifest"])
def test_bad_table_shapes_and_duplicate_inputs_are_rejected(tmp_path, problem):
    root, tables = tmp_path / "input", tmp_path / "output"
    arxiv_id = make_range(root, 1)
    add_references(root, 1, arxiv_id)
    refs = root / "range_1" / "references"
    if problem == "ambiguous":
        (refs / "references.jsonl").write_text("", encoding="utf-8")
    elif problem == "duplicate":
        path = refs / "references.json"
        rows = json.loads(path.read_text())
        path.write_text(json.dumps(rows + rows), encoding="utf-8")
    elif problem == "invalid_id":
        path = refs / "references.json"
        rows = json.loads(path.read_text())
        rows[0]["ref_arxiv_id"] = None
        path.write_text(json.dumps(rows), encoding="utf-8")
    elif problem == "raw_api":
        (refs / "references.json").write_text('{"data": []}', encoding="utf-8")
    else:
        (root / "range_1" / "sources" / "batch_00000.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        run_selected_ranges(root, [1], tmp_path / "working", tables)
    assert not tables.exists()


def test_explicit_output_cannot_replace_different_selection(tmp_path):
    root, tables = tmp_path / "input", tmp_path / "tables"
    for number in (1, 2):
        make_range(root, number)
    run_selected_ranges(root, [1], tmp_path / "working", tables)
    original = (tables / "elements.jsonl").read_bytes()
    with pytest.raises(ValueError, match="--tables-dir"):
        run_selected_ranges(root, [2], tmp_path / "working", tables)
    assert (tables / "elements.jsonl").read_bytes() == original


def test_cli_init_missing_data_and_conflicting_flags(tmp_path, capsys):
    root = tmp_path / "input"
    assert main(["--init-layout", "--input-root", str(root)]) == 0
    assert main(["--ranges", "all", "--input-root", str(root)]) == 1
    assert "No batch_*.tar.gz" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parse_args(["--ranges", "1", "--batch-dir", "other"])
