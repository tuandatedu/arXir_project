"""Offline tests: DOI từ M1 đi tới feature / label của M3."""
from __future__ import annotations

import json

from src.m3_matching.cleaning import prepare_bibtex_record, prepare_reference_record
from src.m3_matching.doi_resolver import build_doi_to_arxiv_map, resolve_arxiv_by_doi
from src.m3_matching.features import feature_names, pair_feature_vector
from src.m3_matching.references_io import (
    enrich_from_tables_dir, enrich_references_with_doi,
)

IDX = feature_names().index("doi_match")


def _pool_row(s2="s1", arxiv="1706.03762"):
    return {"arxiv_id": "2610.00001", "ref_arxiv_id": arxiv, "ref_title": "Attention",
            "ref_authors": ["A"], "ref_submission_date": "2017", "ref_s2_id": s2}


def test_external_ids_snake_case_is_read():
    rec = prepare_reference_record({"ref_title": "T", "external_ids": {"DOI": "10.1/ABC"}})
    assert rec["doi_norm"] == "10.1/abc"


def test_enrich_adds_ref_doi_without_changing_rows():
    pool = [_pool_row("s1"), _pool_row("s2", "2001.00001")]
    raw = [
        {"arxiv_id": "2610.00001", "ref_s2_id": "s1", "ref_doi": "10.1/ABC", "ref_arxiv_id": "1706.03762"},
        {"arxiv_id": "2610.00001", "ref_s2_id": "zz", "ref_doi": "10.9/none", "ref_arxiv_id": None},
    ]
    out = enrich_references_with_doi(pool, raw)
    assert len(out) == 2 and out[0]["ref_doi"] == "10.1/ABC" and "ref_doi" not in out[1]
    assert "ref_doi" not in pool[0]  # không sửa input


def test_doi_match_feature_turns_on_after_enrich(tmp_path):
    (tmp_path / "references_raw_response.json").write_text(json.dumps([
        {"arxiv_id": "2610.00001", "ref_s2_id": "s1", "ref_doi": "https://doi.org/10.1/ABC",
         "ref_arxiv_id": "1706.03762"}]), encoding="utf-8")
    bib = prepare_bibtex_record({"citation_key": "k", "title": "Attention", "authors": ["A B"],
                                 "year": 2017, "doi": "10.1/abc"})
    plain = prepare_reference_record(_pool_row())
    rich = prepare_reference_record(enrich_from_tables_dir([_pool_row()], tmp_path)[0])
    assert pair_feature_vector(bib, plain)[IDX] == 0.0   # trước: DOI không tới được M3
    assert pair_feature_vector(bib, rich)[IDX] == 1.0    # sau: khớp
    wrong = prepare_reference_record({**_pool_row(), "ref_doi": "10.2/zzz"})
    assert pair_feature_vector(bib, wrong)[IDX] == -1.0


def test_missing_raw_file_is_noop(tmp_path):
    pool = [_pool_row()]
    assert enrich_from_tables_dir(pool, tmp_path) == pool


def test_doi_map_uses_cited_paper_not_citing_paper():
    bib_rows = [{"arxiv_id": "2610.00001", "citation_key": "k", "doi": "10.1/x"}]
    assert build_doi_to_arxiv_map(bib_rows) == {}          # bibtex: không có ID bài được cite
    refs = [{"arxiv_id": "2610.00001", "ref_arxiv_id": "1706.03762", "ref_doi": "10.1/X"}]
    m = build_doi_to_arxiv_map(refs)
    assert resolve_arxiv_by_doi("https://doi.org/10.1/x", m) == "1706.03762"
