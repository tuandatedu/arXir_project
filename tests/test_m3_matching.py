"""
Unit tests dành riêng cho phần việc của Người 1 (Milestone 3).
Kiểm tra các nhiệm vụ 1 đến 6:
1. Làm sạch dữ liệu (cleaning.py)
2. Gán nhãn thủ công & quota (labelling.py & manual_tool.py)
3. Gán nhãn tự động heuristic (labelling.py)
4. Vector 14 đặc trưng (features.py)
5. Tạo bảng dữ liệu huấn luyện từ các cặp (dataset.py)
6. Phân chia tập train / valid / test (split.py)
"""

import csv

import pytest
import src.m3_matching.dataset as dataset_module
from src.common.io import read_json, read_jsonl, write_json, write_jsonl
from src.m3_matching.cleaning import (
    normalize_authors,
    normalize_doi,
    normalize_title,
    normalize_year,
    prepare_bibtex_record,
    prepare_reference_record,
)
from src.m3_matching.dataset import build_citation_context_map, build_paper_pairs
from src.m3_matching.features import (
    author_overlap,
    feature_names,
    pair_feature_vector,
    title_similarity,
    year_distance,
)
from src.m3_matching.labelling import (
    auto_match_one,
    auto_label_publication,
    load_labels,
    save_labels,
    validate_label_quota,
)
from src.m3_matching.manual_tool import export_manual_template, import_manual_csv
from src.m3_matching.prepare_dataset import run_preparation_pipeline
from src.m3_matching.split import split_publications


# ---------------------------------------------------------------------------
# 1. Test Làm sạch dữ liệu (cleaning.py)
# ---------------------------------------------------------------------------
def test_normalize_title():
    raw_tex = r"Attention Is All You Need: {\textbf{Transformer}} & Networks"
    cleaned = normalize_title(raw_tex)
    assert "attention is all you need" in cleaned
    assert "transformer" in cleaned
    assert "{" not in cleaned and "}" not in cleaned and "\\" not in cleaned


def test_normalize_authors():
    authors_bib = ["Vaswani, Ashish", "Noam Shazeer", "Niki Parmar et al."]
    norm = normalize_authors(authors_bib)
    assert len(norm) == 3
    assert norm[0] == "vaswani, a"
    assert norm[1] == "shazeer, n"
    assert norm[2] == "parmar, n"


def test_normalize_title_decodes_latex_accents_before_braces():
    # Trước đây {} bị thay bằng space nên "Schr\"{o}dinger" -> "schr o dinger".
    cleaned = normalize_title(r'Schr\"{o}dinger Equation: {\textbf{Quantum}} Mechanics')
    assert cleaned == "schrodinger equation quantum mechanics"
    assert "schr o dinger" not in cleaned


def test_normalize_authors_keeps_name_particles_consistent():
    comma_form = normalize_authors(["van der Berg, Jan"])[0]
    plain_form = normalize_authors(["Jan van der Berg"])[0]
    assert comma_form == plain_form == "van der berg, j"
    assert normalize_authors(["María de la Cruz"])[0] == "de la cruz, m"
    assert normalize_authors(["de la Cruz, María"])[0] == "de la cruz, m"


def test_normalize_year():
    assert normalize_year(2017) == 2017
    assert normalize_year("2017") == 2017
    assert normalize_year("2017-06-12") == 2017
    assert normalize_year("InvalidYear") is None
    assert normalize_year(1700) is None


def test_prepare_records():
    bib = {"arxiv_id": "2310.12345", "citation_key": "v17", "title": "Test Title", "year": "2020"}
    bib_clean = prepare_bibtex_record(bib)
    assert bib_clean["title_norm"] == "test title"
    assert bib_clean["year_norm"] == 2020
    # Đảm bảo không sửa đổi dict gốc
    assert "title_norm" not in bib

    ref = {"arxiv_id": "2310.12345", "ref_arxiv_id": "1706.03762", "ref_title": "Test Title", "ref_submission_date": "2020-01-01"}
    ref_clean = prepare_reference_record(ref)
    assert ref_clean["title_norm"] == "test title"
    assert ref_clean["year_norm"] == 2020


def test_normalize_title_strips_citation_tails():
    raw = (
        "Outcome Monitors: Recovery Affordances for Silent Tool Failures. "
        "arXiv preprint. https://arxiv.org/abs/2608.19303v1"
    )
    assert normalize_title(raw) == "outcome monitors recovery affordances for silent tool failures"


def test_normalize_title_keeps_math_content():
    assert normalize_title("Beyond Top-$k$ Skill Retrieval") == "beyond top k skill retrieval"
    assert normalize_title("Beyond Top-k Skill Retrieval") == "beyond top k skill retrieval"


def test_normalize_title_strips_html_tags():
    assert normalize_title("<i>Attention</i> Is All You Need") == "attention is all you need"


def test_normalize_authors_splits_newlines():
    assert normalize_authors("Vaswani, Ashish\nShazeer, Noam") == [
        "vaswani, a",
        "shazeer, n",
    ]


def test_prepare_reference_normalizes_arxiv_id():
    ref = {"ref_arxiv_id": "arXiv:1706.03762v5", "ref_title": "Attention"}
    assert prepare_reference_record(ref)["ref_arxiv_id_norm"] == "1706.03762"


def test_prepare_bibtex_accepts_alias_columns():
    bib = {
        "bib_title": "Top-$k$ Retrieval",
        "bib_authors": "Doe, Jane",
        "bib_year": "2024",
        "bib_doi": "https://doi.org/10.1/ABC",
    }
    clean = prepare_bibtex_record(bib)
    assert clean["title_norm"] == "top k retrieval"
    assert clean["authors_norm"] == ["doe, j"]
    assert clean["year_norm"] == 2024
    assert clean["doi_norm"] == "10.1/abc"


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1145/ABC.") == "10.1145/abc"
    assert normalize_doi("http://dx.doi.org/10.1145/abc") == "10.1145/abc"
    assert normalize_doi("doi:10.1145/abc") == "10.1145/abc"
    assert normalize_doi("   ") is None
    assert normalize_doi(None) is None
    assert normalize_doi("HTTPS://DOI.ORG/10.1145/ABC?ref=123#section") == "10.1145/abc"
    assert normalize_doi("<https://dx.doi.org/10.1145/ABC?source=x>") == "10.1145/abc"


def test_normalize_year_avoids_ambiguous_metadata_years():
    from src.m3_matching.cleaning import normalize_year

    assert normalize_year("2024-03-17") == 2024
    assert normalize_year("Volume 2020, published 2022") is None
    assert normalize_year("published in 2022") == 2022


def test_reference_doi_from_external_ids():
    ref = {
        "ref_arxiv_id": "1706.03762",
        "ref_title": "Attention Is All You Need",
        "externalIds": {"DOI": "https://doi.org/10.1/XYZ"},
    }
    assert prepare_reference_record(ref)["doi_norm"] == "10.1/xyz"


# ---------------------------------------------------------------------------
# 2 & 3. Test Gán nhãn thủ công & Tự động (labelling.py)
# ---------------------------------------------------------------------------
def test_auto_match_one():
    bib = {"title": "Attention Is All You Need", "authors": ["Vaswani, Ashish"], "year": 2017, "doi": "10.1234/test"}
    refs = [
        {"ref_arxiv_id": "1706.03762", "ref_title": "Attention Is All You Need", "ref_authors": ["Ashish Vaswani"], "ref_submission_date": "2017-06-12", "doi": "10.1234/test"},
        {"ref_arxiv_id": "1801.00000", "ref_title": "Unrelated Work on Vision", "ref_authors": ["LeCun, Yann"], "ref_submission_date": "2018-01-01"},
    ]
    matched = auto_match_one(bib, refs)
    assert matched == "1706.03762"

    unmatched_bib = {"title": "Completely Unknown Paper Not In References"}
    assert auto_match_one(unmatched_bib, refs) is None


def test_auto_match_doi_with_prefix():
    bib = {"title": "Different Title", "doi": "https://doi.org/10.1/ABC"}
    refs = [{"ref_arxiv_id": "ref.9", "ref_title": "Another Title", "doi": "doi:10.1/abc"}]
    assert auto_match_one(bib, refs) == "ref.9"


def test_auto_label_null_records_heuristic_no_match_and_reason():
    ambiguous = auto_label_publication(
        "paper.1",
        [{"citation_key": "k1", "title": "Same Candidate Title"}],
        [
            {"ref_arxiv_id": "ref.1", "ref_title": "Same Candidate Title"},
            {"ref_arxiv_id": "ref.2", "ref_title": "Same Candidate Title"},
        ],
    )[0]
    assert ambiguous["groundtruth_arxiv_id"] is None
    assert ambiguous["label_status"] == "auto_no_match"
    assert ambiguous["null_reason"] == "ambiguous_exact_title_candidates"

    no_candidates = auto_label_publication(
        "paper.2", [{"citation_key": "k1", "title": "Some title"}], []
    )[0]
    assert no_candidates["label_status"] == "auto_no_match"
    assert no_candidates["null_reason"] == "no_candidate_with_arxiv_id"


def test_validate_label_quota():
    # 5 manual papers, mỗi bài 20 entries = 100 entries
    labels = {}
    for i in range(1, 6):
        labels[f"manual_p{i}"] = [
            {"citation_key": f"k{j}", "groundtruth_arxiv_id": f"ref{j}", "source": "manual"}
            for j in range(20)
        ]
    # 2 bài auto
    for i in range(1, 3):
        labels[f"auto_p{i}"] = [
            {"citation_key": f"ak{j}", "groundtruth_arxiv_id": f"aref{j}", "source": "auto"}
            for j in range(10)
        ]

    # Kiểm tra đạt quota với k=1
    validate_label_quota(labels, n_publications_total=20, k=1)

    # Thiếu manual papers (< 5)
    with pytest.raises(ValueError, match="Thiếu manual publications"):
        bad_labels = {k: v for k, v in list(labels.items())[:4]}
        validate_label_quota(bad_labels, n_publications_total=20, k=1)


# ---------------------------------------------------------------------------
# 4. Test Đặc trưng (features.py)
# ---------------------------------------------------------------------------
def test_features_dimensions():
    bib = {"title_norm": "deep residual learning for image recognition", "authors_norm": ["he, k"], "year_norm": 2016}
    ref = {"title_norm": "deep residual learning for image recognition", "authors_norm": ["he, k"], "year_norm": 2016}

    vec = pair_feature_vector(bib, ref)
    names = feature_names()
    assert len(vec) == len(names)
    assert len(vec) == 14  # Đầy đủ 14 đặc trưng
    assert title_similarity(bib, ref) >= 0.99
    assert author_overlap(bib, ref) == 1.0
    assert year_distance(bib, ref) == 0.0


def test_feature_doi_match_normalizes_prefixes():
    bib = {"title_norm": "a paper", "doi": "https://doi.org/10.1/ABC"}
    ref = {"title_norm": "a paper", "doi": "doi:10.1/abc"}
    names = feature_names()
    vec = pair_feature_vector(bib, ref)
    assert vec[names.index("doi_match")] == 1.0


def test_author_first_match_compares_surname_across_name_formats():
    bib = {"title_norm": "same title", "authors_norm": ["Smith, J"]}
    ref = {"title_norm": "same title", "authors_norm": ["Jane Smith"]}
    names = feature_names()
    vec = pair_feature_vector(bib, ref)
    assert vec[names.index("author_first_match")] == 1.0


def test_feature_year_missing_sentinel():
    bib = {"title_norm": "a paper", "year_norm": None}
    ref = {"title_norm": "a paper", "year_norm": 2020}
    assert year_distance(bib, ref) == -1.0
    names = feature_names()
    vec = pair_feature_vector(bib, ref)
    assert vec[names.index("year_diff")] == 99.0
    assert vec[names.index("year_missing")] == 1.0


# ---------------------------------------------------------------------------
# 5. Test Bảng dữ liệu cặp huấn luyện (dataset.py)
# ---------------------------------------------------------------------------
def test_build_paper_pairs():
    arxiv_id = "test.001"
    bibs = [
        {"citation_key": "k1", "title": "Paper One", "authors": ["Author A"], "year": 2021},
        {"citation_key": "k2", "title": "Paper Two", "authors": ["Author B"], "year": 2022},
    ]
    refs = [
        {"ref_arxiv_id": "ref.101", "ref_title": "Paper One", "ref_authors": ["Author A"], "ref_submission_date": "2021"},
        {"ref_arxiv_id": "ref.102", "ref_title": "Paper Extra", "ref_authors": ["Author C"], "ref_submission_date": "2020"},
    ]
    labels = [
        {"citation_key": "k1", "groundtruth_arxiv_id": "ref.101", "source": "manual"},
        {"citation_key": "k2", "groundtruth_arxiv_id": None, "label_status": "unknown", "source": "manual"},
    ]

    pairs = build_paper_pairs(arxiv_id, bibs, refs, labels, partition="train")
    assert len(pairs) == 2  # chỉ entry k1 có nhãn xác định được tạo cặp
    # Cặp k1 - ref.101 phải có label = 1
    match_pairs = [p for p in pairs if p["citation_key"] == "k1" and p["ref_arxiv_id"] == "ref.101"]
    assert match_pairs[0]["label"] == 1
    # Cặp k1 - ref.102 label = 0
    neg_pairs = [p for p in pairs if p["citation_key"] == "k1" and p["ref_arxiv_id"] == "ref.102"]
    assert neg_pairs[0]["label"] == 0
    # k2 có groundtruth None -> bị bỏ khỏi dataset, không biến thành negative
    k2_pairs = [p for p in pairs if p["citation_key"] == "k2"]
    assert k2_pairs == []


def test_gt_null_review_states_and_gt_outside_pool():
    bibs = [{"citation_key": key, "title": "Different title"} for key in ("known_none", "unknown", "outside")]
    refs = [
        {"ref_arxiv_id": "ref.1", "ref_title": "Candidate One"},
        {"ref_arxiv_id": "ref.3", "ref_title": "Candidate Two"},
    ]
    labels = [
        {"citation_key": "known_none", "groundtruth_arxiv_id": None, "label_status": "no_match", "source": "manual"},
        {"citation_key": "unknown", "groundtruth_arxiv_id": None, "label_status": "unknown", "source": "manual"},
        {"citation_key": "outside", "groundtruth_arxiv_id": "ref.2", "label_status": "no_match", "source": "manual"},
    ]
    pairs = build_paper_pairs("test.001", bibs, refs, labels, partition="train")

    # unknown không sinh pair; no_match và GT ngoài pool sinh hàng toàn 0.
    assert sorted({p["citation_key"] for p in pairs}) == ["known_none", "outside"]
    assert all(p["label"] == 0 for p in pairs)
    assert len([p for p in pairs if p["citation_key"] == "known_none"]) == 2

    outside = [p for p in pairs if p["citation_key"] == "outside"]
    assert len(outside) == 2
    assert {p["ref_arxiv_id"] for p in outside} == {"ref.1", "ref.3"}
    assert all(p["groundtruth_arxiv_id"] == "ref.2" for p in outside)
    with pytest.raises(ValueError, match="no_match.*candidate pool"):
        build_paper_pairs(
            "test.001", [{"citation_key": "bad", "title": "x"}], refs,
            [{"citation_key": "bad", "groundtruth_arxiv_id": "ref.1", "label_status": "no_match", "source": "manual"}],
            partition="train",
        )

    with pytest.raises(ValueError, match="unknown.*groundtruth_arxiv_id"):
        build_paper_pairs(
            "test.001", [{"citation_key": "bad", "title": "x"}], refs,
            [{"citation_key": "bad", "groundtruth_arxiv_id": "ref.1", "label_status": "unknown"}],
            partition="train",
        )


def test_build_paper_pairs_rejects_feature_dimension_mismatch(monkeypatch):
    monkeypatch.setattr(dataset_module, "pair_feature_vector", lambda *args, **kwargs: [0.0])
    with pytest.raises(ValueError, match="Feature dimension mismatch"):
        build_paper_pairs(
            "test.001",
            [{"citation_key": "k1", "title": "x"}],
            [{"ref_arxiv_id": "ref.1", "ref_title": "candidate"}],
            [{"citation_key": "k1", "groundtruth_arxiv_id": "ref.1", "label_status": "match"}],
            partition="train",
        )


def _write_pipeline_fixture(tmp_path):
    """Dataset nhỏ đủ quota: 5 manual × 20 + 2 auto × 10."""
    tables = tmp_path / "tables"
    labels_dir = tmp_path / "labels"
    tables.mkdir()

    bib_rows = []
    ref_rows = []
    manual_labels = {}
    for i in range(1, 6):
        pid = f"man.{i:03d}"
        keys = [f"k{j}" for j in range(20)]
        for key in keys:
            bib_rows.append({
                "arxiv_id": pid, "citation_key": key, "title": f"Title {key}",
                "authors": ["A, B"], "year": 2020,
            })
        for ref_id in ("ref.1", "ref.2", "ref.3"):
            ref_rows.append({
                "arxiv_id": pid, "ref_arxiv_id": ref_id,
                "ref_title": f"Ref {ref_id}", "ref_authors": ["A, B"],
                "ref_submission_date": "2020-01-01",
            })
        rows = []
        for j, key in enumerate(keys):
            if i == 1 and j < 2:
                rows.append({"citation_key": key, "groundtruth_arxiv_id": None, "label_status": "no_match", "source": "manual"})
            elif i == 2 and j == 0:
                rows.append({"citation_key": key, "groundtruth_arxiv_id": "ref.outside", "label_status": "match", "source": "manual"})
            else:
                rows.append({"citation_key": key, "groundtruth_arxiv_id": "ref.1", "label_status": "match", "source": "manual"})
        manual_labels[pid] = rows

    auto_labels = {}
    for i in range(1, 3):
        pid = f"auto.{i:03d}"
        keys = [f"ak{j}" for j in range(10)]
        for j, key in enumerate(keys):
            bib_rows.append({
                "arxiv_id": pid, "citation_key": key,
                "title": "Ref ref.1" if j < 5 else f"Auto {key}",
                "authors": ["C, D"], "year": 2021,
            })
        for ref_id in ("ref.1", "ref.2", "ref.3"):
            ref_rows.append({
                "arxiv_id": pid, "ref_arxiv_id": ref_id,
                "ref_title": f"Ref {ref_id}", "ref_authors": ["C, D"],
                "ref_submission_date": "2021-01-01",
            })
        rows = []
        for j, key in enumerate(keys):
            if j < 5:
                rows.append({"citation_key": key, "groundtruth_arxiv_id": "ref.1", "label_status": "match", "source": "auto"})
            else:
                rows.append({
                    "citation_key": key, "groundtruth_arxiv_id": None,
                    "label_status": "unknown",
                    "null_reason": "no_match_meets_heuristic_threshold",
                    "source": "auto",
                })
        auto_labels[pid] = rows

    write_json(tables / "bibtex.json", bib_rows)
    write_json(tables / "references.json", ref_rows)
    for pid, rows in manual_labels.items():
        save_labels(pid, rows, labels_dir)
    for pid, rows in auto_labels.items():
        save_labels(pid, rows, labels_dir)
    return tables, labels_dir


def test_pipeline_query_stats_match_parquet(tmp_path):
    import pandas as pd

    tables, labels_dir = _write_pipeline_fixture(tmp_path)
    out_dir = tmp_path / "prepared"
    summary = run_preparation_pipeline(
        tables_dir=tables,
        labels_dir=labels_dir,
        k=1,
        seed=42,
        prepared_dataset_dir=out_dir,
    )
    report = summary["audit"]
    assert report["query_totals"] == {
        "total": 120,
        "match": 107,
        "no_match": 2,
        "auto_no_match": 10,
        "unknown": 0,
        "gt_outside_candidate_pool": 1,
        "queries_with_pairs": 120,
        "queries_without_pairs": 0,
    }
    assert report["evaluation_scope"]["candidate_coverage"] == pytest.approx(107 / 108)
    assert report["evaluation_scope"]["mrr_at_5_evaluated_denominator"] == 107
    assert report["evaluation_scope"]["mrr_at_5_strict_denominator"] == 120
    assert report["automatic_no_match_queries"] == 10
    assert report["automatic_queries_unresolved"] == 0
    assert report["automatic_labeling_complete"] is True
    assert report["evaluation_scope"]["by_partition"]["test"]["mrr_at_5_strict_denominator"] == report["query_stats_by_partition"]["test"]["total"]

    frame = pd.read_parquet(out_dir / "dataset_pairs.parquet")
    pair_keys = set(zip(frame["arxiv_id"], frame["citation_key"]))
    assert len(pair_keys) == report["queries_with_candidate_pairs"] == 120
    assert int(frame["label"].sum()) == 107

    # Automatic abstentions become auditable all-zero heuristic labels.
    auto_no_match_keys = {(f"auto.{i:03d}", f"ak{j}") for i in (1, 2) for j in range(5, 10)}
    assert auto_no_match_keys.issubset(pair_keys)
    auto_negatives = frame[
        frame.apply(lambda row: (row["arxiv_id"], row["citation_key"]) in auto_no_match_keys, axis=1)
    ]
    assert len(auto_negatives) == 30 and (auto_negatives["label"] == 0).all()

    # no_match và GT ngoài pool đều là hàng toàn 0, giữ GT thật.
    no_match = frame[(frame["arxiv_id"] == "man.001") & frame["citation_key"].isin(["k0", "k1"])]
    assert len(no_match) == 6 and (no_match["label"] == 0).all()
    outside = frame[(frame["arxiv_id"] == "man.002") & (frame["citation_key"] == "k0")]
    assert len(outside) == 3 and (outside["label"] == 0).all()
    assert set(outside["groundtruth_arxiv_id"]) == {"ref.outside"}

    # Thống kê theo split cộng lại phải khớp tổng.
    by_partition = report["query_stats_by_partition"]
    assert sum(v["total"] for v in by_partition.values()) == 120
    assert sum(v["queries_with_pairs"] for v in by_partition.values()) == 120


def test_manual_import_preserves_unknown_and_no_match(tmp_path):
    csv_path = tmp_path / "review.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id", "suggested_ref_arxiv_id", "review_status"])
        writer.writeheader()
        writer.writerow({"citation_key": "unknown", "suggested_ref_arxiv_id": "ref.1", "review_status": "unknown"})
        writer.writerow({"citation_key": "none", "suggested_ref_arxiv_id": "ref.2", "review_status": "no_match"})
    rows = read_json(import_manual_csv(csv_path, "test.007", labels_dir=tmp_path / "labels"))
    assert [(r["citation_key"], r["label_status"], r["groundtruth_arxiv_id"]) for r in rows] == [
        ("unknown", "unknown", None), ("none", "no_match", None)
    ]


def test_build_paper_pairs_dedups_reference_arxiv_ids():
    arxiv_id = "test.002"
    bibs = [{"citation_key": "k1", "title": "Paper One", "authors": ["Author A"], "year": 2021}]
    refs = [
        {"ref_arxiv_id": "ref.101", "ref_title": "Paper One", "ref_authors": ["Author A"], "ref_submission_date": "2021"},
        {"ref_arxiv_id": "ref.101", "ref_title": "Paper One (duplicate row)", "ref_authors": ["Author A"], "ref_submission_date": "2021"},
        {"ref_arxiv_id": "ref.102", "ref_title": "Paper Extra", "ref_authors": ["Author C"], "ref_submission_date": "2020"},
    ]
    labels = [{"citation_key": "k1", "groundtruth_arxiv_id": "ref.101", "source": "manual"}]

    pairs = build_paper_pairs(arxiv_id, bibs, refs, labels, partition="train")
    assert len(pairs) == 2  # 1 bib x 2 unique refs, không nhân đôi ref.101
    assert sorted(p["ref_arxiv_id"] for p in pairs) == ["ref.101", "ref.102"]


def test_build_citation_context_and_cite_count_feature():
    elements = [
        {"arxiv_id": "test.003", "kind": "paragraph", "content": r"See \cite{k1,k2} and \citep[p.~2]{k1}."},
        {"arxiv_id": "test.003", "kind": "sentence", "content": r"Again \citet*{k1}."},
    ]
    contexts = build_citation_context_map(elements)
    assert contexts["test.003"]["k1"]["cite_count"] == 3.0
    assert contexts["test.003"]["k2"]["cite_count"] == 1.0

    bibs = [{"citation_key": "k1", "title": "Paper One", "authors": ["Author A"], "year": 2021}]
    refs = [{"ref_arxiv_id": "ref.101", "ref_title": "Paper One", "ref_authors": ["Author A"], "ref_submission_date": "2021"}]
    labels = [{"citation_key": "k1", "groundtruth_arxiv_id": "ref.101", "source": "manual"}]

    pairs = build_paper_pairs(
        "test.003", bibs, refs, labels, partition="train",
        citation_context=contexts["test.003"],
    )
    assert pairs[0]["cite_count"] == 3.0


def test_manual_template_does_not_autofill_groundtruth(tmp_path):
    bib_path = tmp_path / "bibtex.jsonl"
    ref_path = tmp_path / "references.jsonl"
    write_jsonl(bib_path, [{
        "arxiv_id": "test.004",
        "citation_key": "k1",
        "bib_title": "Attention Is All You Need",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani, Ashish"],
        "year": 2017,
    }])
    write_jsonl(ref_path, [{
        "arxiv_id": "test.004",
        "ref_arxiv_id": "1706.03762",
        "ref_title": "Attention Is All You Need",
        "ref_authors": ["Ashish Vaswani"],
        "ref_submission_date": "2017-06-12",
    }])

    out_csv = tmp_path / "test.004.csv"
    export_manual_template("test.004", out_csv, bibtex_path=bib_path, references_path=ref_path)

    with out_csv.open(encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["suggested_ref_arxiv_id"] == "1706.03762"
    assert row["suggested_score"]
    assert row["groundtruth_arxiv_id"] == ""
    assert row["review_status"] == "unknown"
    assert "is_verified" not in row


def test_import_manual_csv_uses_only_nonempty_groundtruth(tmp_path):
    csv_path = tmp_path / "test.005.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id", "suggested_ref_arxiv_id"])
        writer.writeheader()
        writer.writerow({"citation_key": "k1", "groundtruth_arxiv_id": "ref.1", "suggested_ref_arxiv_id": "ref.9"})
        writer.writerow({"citation_key": "k2", "groundtruth_arxiv_id": "", "suggested_ref_arxiv_id": "ref.2"})

    labels_dir = tmp_path / "labels"
    out_file = import_manual_csv(csv_path, "test.005", labels_dir=labels_dir)
    rows = read_json(out_file)
    assert [r["citation_key"] for r in rows] == ["k1", "k2"]
    assert rows[0]["groundtruth_arxiv_id"] == "ref.1"
    assert rows[1]["label_status"] == "unknown"

    legacy_csv = tmp_path / "test.006.csv"
    with legacy_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id"])
        writer.writeheader()
        writer.writerow({"citation_key": "k1", "groundtruth_arxiv_id": "ref.1"})
    legacy_output = import_manual_csv(legacy_csv, "test.006", labels_dir=labels_dir)
    assert read_json(legacy_output)[0]["groundtruth_arxiv_id"] == "ref.1"


def test_manual_import_review_status(tmp_path):
    csv_path = tmp_path / "verified.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["citation_key", "groundtruth_arxiv_id", "suggested_ref_arxiv_id", "review_status"],
        )
        writer.writeheader()
        writer.writerow({"citation_key": "match", "groundtruth_arxiv_id": "ref.1", "suggested_ref_arxiv_id": "ref.9", "review_status": "match"})
        writer.writerow({"citation_key": "outside", "groundtruth_arxiv_id": "ref.8", "suggested_ref_arxiv_id": "ref.9", "review_status": "no_match"})
        writer.writerow({"citation_key": "none", "groundtruth_arxiv_id": "", "suggested_ref_arxiv_id": "ref.2", "review_status": "no_match"})
        writer.writerow({"citation_key": "uncertain", "groundtruth_arxiv_id": "", "suggested_ref_arxiv_id": "ref.3", "review_status": "unknown"})
        writer.writerow({"citation_key": "pending", "groundtruth_arxiv_id": "", "suggested_ref_arxiv_id": "ref.4", "review_status": "unknown"})

    rows = read_json(import_manual_csv(csv_path, "test.008", labels_dir=tmp_path / "labels"))
    assert [(r["label_status"], r["groundtruth_arxiv_id"]) for r in rows] == [
        ("match", "ref.1"),
        ("no_match", "ref.8"),
        ("no_match", None),
        ("unknown", None),
        ("unknown", None),
    ]

    invalid_csv = tmp_path / "invalid_status.csv"
    with invalid_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id", "review_status"])
        writer.writeheader()
        writer.writerow({"citation_key": "k1", "groundtruth_arxiv_id": "ref.1", "review_status": "unknown"})
    with pytest.raises(ValueError, match="review_status"):
        import_manual_csv(invalid_csv, "test.009", labels_dir=tmp_path / "labels")

# ---------------------------------------------------------------------------
# 6. Test Phân chia tập (split.py)
# ---------------------------------------------------------------------------
def test_split_publications():
    labels = {
        f"man_{i}": [{"citation_key": "k1", "source": "manual"}] for i in range(5)
    }
    labels.update({
        f"auto_{i}": [{"citation_key": "k1", "source": "auto"}] for i in range(3)
    })

    part_map = split_publications(labels, seed=42, k=1)
    test_papers = [pid for pid, p in part_map.items() if p == "test"]
    valid_papers = [pid for pid, p in part_map.items() if p == "valid"]
    train_papers = [pid for pid, p in part_map.items() if p == "train"]

    # Test phải có đúng 1 manual + 1 auto
    assert len(test_papers) == 2
    assert any(p.startswith("man_") for p in test_papers)
    assert any(p.startswith("auto_") for p in test_papers)

    # Valid phải có đúng 1 manual + 1 auto
    assert len(valid_papers) == 2
    assert any(p.startswith("man_") for p in valid_papers)
    assert any(p.startswith("auto_") for p in valid_papers)

    # Train chứa phần còn lại
    assert len(train_papers) == 4


def test_split_rejects_invalid_k():
    with pytest.raises(ValueError, match="k phải >= 1"):
        split_publications({}, seed=42, k=0)


def test_build_paper_pairs_normalizes_gt_version_suffix():
    from src.m3_matching.dataset import build_paper_pairs

    bibs = [
        {"arxiv_id": "2401.00001", "citation_key": "k1", "title": "Paper A", "authors": ["A, B"], "year": 2023},
    ]
    refs = [
        {"arxiv_id": "2401.00001", "ref_arxiv_id": "2301.12345", "ref_title": "Paper A", "ref_authors": ["A, B"], "ref_submission_date": "2023-01-01"},
    ]
    labels = [
        {"citation_key": "k1", "groundtruth_arxiv_id": "arXiv:2301.12345v2", "source": "manual"},
    ]
    pairs = build_paper_pairs("2401.00001", bibs, refs, labels, partition="test")
    assert len(pairs) == 1
    assert pairs[0]["groundtruth_arxiv_id"] == "2301.12345"
    assert pairs[0]["label"] == 1
