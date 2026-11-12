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
from src.common.io import read_json, read_jsonl, write_jsonl
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
    load_labels,
    save_labels,
    validate_label_quota,
)
from src.m3_matching.manual_tool import export_manual_template, import_manual_csv
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


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1145/ABC.") == "10.1145/abc"
    assert normalize_doi("http://dx.doi.org/10.1145/abc") == "10.1145/abc"
    assert normalize_doi("doi:10.1145/abc") == "10.1145/abc"
    assert normalize_doi("   ") is None
    assert normalize_doi(None) is None


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
    with pytest.raises(ValueError, match="Thiếu số lượng bài gán nhãn thủ công"):
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
        {"citation_key": "k2", "groundtruth_arxiv_id": None, "source": "manual"},
    ]

    pairs = build_paper_pairs(arxiv_id, bibs, refs, labels, partition="train")
    assert len(pairs) == 4  # 2 bibs x 2 refs
    # Cặp k1 - ref.101 phải có label = 1
    match_pairs = [p for p in pairs if p["citation_key"] == "k1" and p["ref_arxiv_id"] == "ref.101"]
    assert match_pairs[0]["label"] == 1
    # Cặp k1 - ref.102 label = 0
    neg_pairs = [p for p in pairs if p["citation_key"] == "k1" and p["ref_arxiv_id"] == "ref.102"]
    assert neg_pairs[0]["label"] == 0
    # k2 có groundtruth None -> mọi cặp đều label = 0
    k2_pairs = [p for p in pairs if p["citation_key"] == "k2"]
    assert all(p["label"] == 0 for p in k2_pairs)


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
    assert row["is_verified"] == "NO"


def test_import_manual_csv_requires_verified_rows(tmp_path):
    csv_path = tmp_path / "test.005.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id", "is_verified"])
        writer.writeheader()
        writer.writerow({"citation_key": "k1", "groundtruth_arxiv_id": "ref.1", "is_verified": "YES"})
        writer.writerow({"citation_key": "k2", "groundtruth_arxiv_id": "ref.2", "is_verified": "NO"})

    labels_dir = tmp_path / "labels"
    out_file = import_manual_csv(csv_path, "test.005", labels_dir=labels_dir)
    rows = read_json(out_file)
    assert [r["citation_key"] for r in rows] == ["k1"]
    assert rows[0]["groundtruth_arxiv_id"] == "ref.1"

    # Chế độ bỏ qua kiểm tra dùng cho CSV cũ không có cột is_verified.
    out_file_all = import_manual_csv(
        csv_path, "test.005", labels_dir=labels_dir, require_verified=False
    )
    assert len(read_json(out_file_all)) == 2

    unverified_only = tmp_path / "test.006.csv"
    with unverified_only.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["citation_key", "groundtruth_arxiv_id", "is_verified"])
        writer.writeheader()
        writer.writerow({"citation_key": "k1", "groundtruth_arxiv_id": "ref.1", "is_verified": "NO"})
    with pytest.raises(ValueError, match="Không có nhãn hợp lệ"):
        import_manual_csv(unverified_only, "test.006", labels_dir=labels_dir)


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
