"""Regression tests tổng hợp; không đọc snapshot thật hoặc huấn luyện mô hình."""

import numpy as np
import pandas as pd
import pytest

from scripts.run_weighted_baseline import evaluate_baselines, load_pairs, weighted_scores


def query(key="q", n=2, positive=1, arxiv_id="paper"):
    gt = f"r{positive}" if positive is not None else None
    return [{
        "arxiv_id": arxiv_id, "citation_key": key, "ref_arxiv_id": f"r{i}",
        "groundtruth_arxiv_id": gt, "label": int(i == positive),
        "title_levenshtein": 0.9 - i * 0.1, "author_jaccard": 0.0, "year_exact": 0.0,
    } for i in range(n)]


def test_fixed_formula_and_missing_year_sentinel():
    frame = pd.DataFrame({"title_levenshtein": [0.8, 0.8, 0.0],
                          "author_jaccard": [0.5, 0.5, 0.0], "year_exact": [1.0, -1.0, -1.0]})
    assert weighted_scores(frame) == pytest.approx([0.76, 0.56, -0.1])


def test_descending_ranking_and_real_positive_improvement():
    frame = pd.DataFrame(query())
    frame.loc[1, ["author_jaccard", "year_exact"]] = [1.0, 1.0]
    before = frame.copy(deep=True)
    result = evaluate_baselines(frame)
    row = result["queries"][0]
    assert row["title_only"]["positive_rank_full"] == 2
    assert row["weighted"]["positive_rank_full"] == 1
    assert row["weighted"]["top1_ref_arxiv_id"] == "r1"
    assert result["comparison"]["improved_positive_queries"] == 1
    pd.testing.assert_frame_equal(frame, before)


def test_ties_keep_input_order_not_id_or_dataframe_index():
    rows = query(n=3, positive=0)
    for row, ref in zip(rows, ["z", "b", "a"]):
        row.update(ref_arxiv_id=ref, groundtruth_arxiv_id="z", title_levenshtein=0.5)
    frame = pd.DataFrame(rows, index=[100, 2, 2])
    one = evaluate_baselines(frame)
    two = evaluate_baselines(frame)
    assert one == two
    for baseline in ["title_only", "weighted"]:
        assert [r["ref_arxiv_id"] for r in one["queries"][0][baseline]["top5"]] == ["z", "b", "a"]


def test_null_gt_is_zero_rr_and_conditional_metrics_are_undefined_without_positives():
    result = evaluate_baselines(pd.DataFrame(query(positive=None)))
    assert result["null_gt_queries"] == 1
    assert result["positive_queries"] == 0
    for baseline in ["title_only", "weighted"]:
        assert result[baseline]["mrr_at_5"] == 0.0
        assert result[baseline]["mrr_at_5_positive_only"] is None
        assert result[baseline]["hit_at_1_positive_only"] is None


def test_mrr_top5_cutoff_and_conditional_denominators():
    frame = pd.DataFrame(query("top1", 6, 0) + query("top3", 6, 2)
                         + query("top6", 6, 5) + query("null", 6, None))
    result = evaluate_baselines(frame)
    for baseline in ["title_only", "weighted"]:
        assert result[baseline]["mrr_at_5"] == pytest.approx((1 + 1/3) / 4)
        assert result[baseline]["mrr_at_5_positive_only"] == pytest.approx((1 + 1/3) / 3)
        assert result[baseline]["hit_at_1_positive_only"] == pytest.approx(1/3)
        assert result[baseline]["hit_at_5_positive_only"] == pytest.approx(2/3)
        last = next(r for r in result["queries"] if r["citation_key"] == "top6")
        assert last[baseline]["positive_rank_full"] == 6
        assert last[baseline]["correct_rank_at_5"] is None
        assert last[baseline]["rr_at_5"] == 0.0


def test_query_key_includes_publication_id():
    frame = pd.DataFrame(query("same", arxiv_id="p1") + query("same", arxiv_id="p2"))
    assert evaluate_baselines(frame)["total_queries"] == 2


def test_scoring_never_reads_labels_or_gt():
    frame = pd.DataFrame(query())
    scores = weighted_scores(frame)
    frame["label"] = [1, 0]
    frame["groundtruth_arxiv_id"] = "a different GT"
    assert weighted_scores(frame) == pytest.approx(scores)


@pytest.mark.parametrize("column", ["title_levenshtein", "author_jaccard", "year_exact"])
def test_missing_feature_is_rejected(column):
    frame = pd.DataFrame(query()).drop(columns=column)
    with pytest.raises(ValueError, match="Thiếu cột"):
        weighted_scores(frame)


@pytest.mark.parametrize("column,value", [
    ("title_levenshtein", np.nan), ("author_jaccard", np.inf),
    ("year_exact", -np.inf), ("year_exact", np.nan),
    ("title_levenshtein", -0.1), ("title_levenshtein", 1.1),
    ("author_jaccard", 2.0), ("year_exact", 0.5),
    ("title_levenshtein", "không phải số"), ("author_jaccard", True),
    ("year_exact", 1j), ("title_levenshtein", None),
])
def test_invalid_numeric_features_are_rejected(column, value):
    frame = pd.DataFrame(query())
    if isinstance(value, (str, bool, complex)):
        frame[column] = value
    else:
        frame.loc[0, column] = value
    with pytest.raises(ValueError):
        evaluate_baselines(frame)


def test_conflicting_gt_labels_and_duplicate_candidates_are_rejected():
    frame = pd.DataFrame(query())
    frame.loc[0, "label"] = 1
    with pytest.raises(ValueError, match="nhiều hơn một Positive"):
        evaluate_baselines(frame)
    frame = pd.DataFrame(query())
    frame.loc[0, "ref_arxiv_id"] = "r1"
    with pytest.raises(ValueError, match="trùng"):
        evaluate_baselines(frame)


def test_known_gt_outside_pool_keeps_zero_rr_instead_of_inventing_positive():
    frame = pd.DataFrame(query(positive=None))
    frame["groundtruth_arxiv_id"] = "not-in-pool"
    result = evaluate_baselines(frame)
    assert result["known_gt_without_positive_queries"] == 1
    assert result["weighted"]["mrr_at_5"] == 0.0


def test_parquet_loader_reads_only_required_columns(tmp_path):
    frame = pd.DataFrame(query())
    frame["unused_feature"] = "không cần đọc"
    path = tmp_path / "sample.parquet"
    frame.to_parquet(path, index=False)
    loaded = load_pairs(path)
    assert "unused_feature" not in loaded
    assert evaluate_baselines(loaded)["total_pairs"] == 2


def test_parquet_missing_feature_is_rejected(tmp_path):
    path = tmp_path / "missing.parquet"
    pd.DataFrame(query()).drop(columns="author_jaccard").to_parquet(path, index=False)
    with pytest.raises(ValueError, match="thiếu cột"):
        load_pairs(path)
