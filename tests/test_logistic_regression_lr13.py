"""Synthetic tests for the LR13 replacement; no real Parquet and no Test split."""
import numpy as np
import pandas as pd
import pytest

from scripts.train_logistic_regression import FEATURES, evaluate_lr, train_lr


def _features(i: int) -> dict:
    vals = {name: float((i + j) % 5) / 5 for j, name in enumerate(FEATURES)}
    vals["year_diff"] = float(i % 3)
    vals["year_exact"] = float(i % 2)
    vals["year_missing"] = 0.0
    vals["cite_count"] = float(i % 4)
    return vals


def _train_rows() -> pd.DataFrame:
    return pd.DataFrame([dict(_features(i), label=int(i % 4 == 0)) for i in range(40)])


def _valid_rows() -> pd.DataFrame:
    rows = []
    for query, gt in [("citation1", "ref1"), ("citation2", None)]:
        for i in range(5):
            row = _features(i)
            row.update(arxiv_id="paper", citation_key=query, ref_arxiv_id=f"ref{i}",
                       groundtruth_arxiv_id=gt, label=int(gt is not None and f"ref{i}" == gt))
            rows.append(row)
    return pd.DataFrame(rows)


def test_lr13_feature_contract():
    assert len(FEATURES) == 13
    assert "doi_match" not in FEATURES
    assert len(set(FEATURES)) == 13


def test_lr13_smoke_and_same_validation_metrics():
    model, train_stats = train_lr(_train_rows())
    assert train_stats["pairs"] == 40
    assert train_stats["positive_pairs"] == 10
    results, top5, queries = evaluate_lr(model, _valid_rows())
    assert results["total_pairs"] == 10
    assert results["total_queries"] == 2
    assert results["positive_queries"] == 1
    assert results["null_gt_queries"] == 1
    assert len(top5) == 10
    assert len(queries) == 2
    assert results["lr13"]["mrr_at_5"] <= 0.5 + 1e-12  # ceiling: 1 positive query / 2 queries
    assert set(top5["rank"].unique()) == {1, 2, 3, 4, 5}


def test_lr13_rejects_nonfinite_train():
    frame = _train_rows()
    frame.loc[0, "title_exact"] = np.nan
    with pytest.raises(ValueError, match="NaN|Inf"):
        train_lr(frame)
