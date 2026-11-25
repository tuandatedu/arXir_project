"""Synthetic, CPU-only tests for scripts.train_lightgbm; no real datasets/Test."""
import numpy as np
import pandas as pd
import pytest

from scripts.train_lightgbm import FEATURES, evaluate_lgbm, feature_importance_frame, train_lgbm
from scripts.train_logistic_regression import FEATURES as LR_FEATURES


def _features(i: int) -> dict:
    d = {name: float((i + j) % 5) / 5 for j, name in enumerate(FEATURES)}
    d["year_diff"] = float(i % 3)
    d["year_exact"] = float(i % 2)
    d["year_missing"] = 0.0
    d["cite_count"] = float(i % 4)
    return d


def _train():
    return pd.DataFrame([dict(_features(i), label=int(i % 4 == 0)) for i in range(100)])


def _valid():
    rows = []
    for citation, gt in [("citation1", "ref1"), ("citation2", None)]:
        for i in range(5):
            rows.append(dict(_features(i), arxiv_id="paper", citation_key=citation,
                             ref_arxiv_id=f"ref{i}", groundtruth_arxiv_id=gt,
                             label=int(gt is not None and f"ref{i}" == gt)))
    return pd.DataFrame(rows)


def test_features_match_lr13():
    assert FEATURES == LR_FEATURES
    assert len(FEATURES) == 13
    assert "doi_match" not in FEATURES


def test_train_and_evaluate_synthetic():
    model, stats = train_lgbm(_train(), n_jobs=1, min_child_samples=5, n_estimators=20)
    assert stats["pairs"] == 100
    assert stats["positive_pairs"] == 25
    report, top5, queries = evaluate_lgbm(model, _valid())
    assert report["total_pairs"] == 10
    assert report["total_queries"] == 2
    assert report["null_gt_queries"] == 1
    assert report["positive_queries"] == 1
    assert len(top5) == 10
    assert len(queries) == 2
    assert set(top5["rank"]) == {1, 2, 3, 4, 5}
    assert report["lgbm13"]["mrr_at_5"] <= 0.5 + 1e-12
    assert set(feature_importance_frame(model)["feature"]) == set(FEATURES)


def test_train_rejects_nan():
    frame = _train()
    frame.loc[0, "title_exact"] = np.nan
    with pytest.raises(ValueError, match="NaN|Inf"):
        train_lgbm(frame, n_jobs=1, n_estimators=5)


def test_train_rejects_single_class():
    frame = _train()
    frame["label"] = 0
    with pytest.raises(ValueError, match="hai nhãn"):
        train_lgbm(frame, n_jobs=1, n_estimators=5)
