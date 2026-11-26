"""Small, isolated tests. Never load the real multi-million-pair data or Test labels to fit."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.m3_global5.M3_GLOBAL5_TRAIN_VALIDATE import FEATURES, evaluate_models

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/m3_global5"
RESULTS = ROOT / "results/m3_global5"


class DummyBinaryModel:
    classes_ = np.array([0, 1])

    def predict_proba(self, X):
        x = np.asarray(X)[:, 0].astype(float)
        return np.column_stack((1.0 - x, x))


def row(q, ref, score, gt=None):
    d = {f: 0.0 for f in FEATURES}
    d.update({
        "arxiv_id": "paper_a", "citation_key": q,
        "ref_arxiv_id": ref, "groundtruth_arxiv_id": gt,
        "label": int(gt is not None and gt == ref),
        "title_levenshtein": score,
    })
    return d


def models():
    m = DummyBinaryModel()
    return {"LR13": m, "LGBM13": m}


def test_fixed_feature_contract():
    assert len(FEATURES) == 13
    assert "doi_match" not in FEATURES
    assert len(FEATURES) == len(set(FEATURES))


def test_positive_and_null_query_mrr_and_stable_ties():
    data = [
        row("q1", "r0", 0.2, gt="r1"),
        row("q1", "r1", 0.9, gt="r1"),
        row("q2", "z", 0.5),
        row("q2", "a", 0.5),
    ]
    metrics, queries, tops, disagreement = evaluate_models(pd.DataFrame(data), models())
    for m in ("B1", "B2", "LR13", "LGBM13"):
        assert metrics[m]["queries"] == 2
        assert metrics[m]["positive_queries"] == 1
        assert metrics[m]["gt_null_queries"] == 1
        assert metrics[m]["mrr_at_5_all"] == pytest.approx(0.5)
        assert metrics[m]["mrr_at_5_positive_only"] == pytest.approx(1.0)
        assert [x["ref_arxiv_id"] for x in tops if x["method"] == m and x["citation_key"] == "q2"] == ["z", "a"]
    assert disagreement == 0
    assert len(queries) == 2


def test_known_gt_absent_is_not_null():
    metrics, queries, _, _ = evaluate_models(pd.DataFrame([
        row("absent", "r0", 0.6, gt="elsewhere"),
        row("absent", "r1", 0.8, gt="elsewhere"),
    ]), models())
    assert metrics["LR13"]["known_gt_outside_pool"] == 1
    assert metrics["LR13"]["gt_null_queries"] == 0
    assert queries[0]["groundtruth_arxiv_id"] == "elsewhere"
    assert metrics["LR13"]["mrr_at_5_all"] == 0.0


def test_inconsistent_pair_labels_are_rejected():
    data = [row("q", "r0", 0.2, gt="r1"), row("q", "r1", 0.9, gt="r1")]
    data[0]["label"] = 1
    with pytest.raises(ValueError, match="Invalid label|Wrong pair labels"):
        evaluate_models(pd.DataFrame(data), models())


def test_frozen_split_and_manifests_agree():
    sm = json.loads((CONFIG / "global5_split_manifest.json").read_text(encoding="utf-8"))
    dp = json.loads((RESULTS / "global5_prepared_manifest.json").read_text(encoding="utf-8"))
    ml = json.loads((RESULTS / "global5_pretest_model_lock.json").read_text(encoding="utf-8"))
    tt = json.loads((RESULTS / "global5_test_metrics.json").read_text(encoding="utf-8"))
    pp = json.loads((RESULTS / "global5_predictions_manifest.json").read_text(encoding="utf-8"))
    split_hash = hashlib.sha256((CONFIG / "global5_publication_split.csv").read_bytes()).hexdigest()
    assert split_hash == sm["split_csv_sha256"], "Split bytes were changed by Git line ending conversion"
    assert sm["status"] == dp["status"] == ml["status"] == tt["status"] == pp["status"] == "PASS"
    assert sm["split_csv_sha256"] == dp["split_csv_sha256"] == ml["global5_split_csv_sha256"] == pp["split_csv_sha256"]
    assert ml["models"]["LR13"]["sha256"] == pp["model_sha256"]
    assert dp["partition"]["test"]["sha256"] == tt["test_sha256"]
    assert dp["partition"]["train"]["sha256"] == ml["train_sha256"]
    assert dp["partition"]["valid"]["sha256"] == ml["valid_sha256"]
    assert dp["all_pairs"] == sum(dp["partition"][p]["pairs"] for p in ("train", "valid", "test")) == 23_231_146
    assert dp["all_queries"] == pp["predictions_rows"] == 790_862
    assert pp["partition_query_counts"] == {p: dp["partition"][p]["queries"] for p in ("train", "valid", "test")}
    assert len(pp["schema"]) == 9 and pp["schema"][-1] == "cand_5"
    assert pp["predictions_sha256"] == "db02fd5eb79b06b1d67ac4cae619fce49523f066372dd630a2986b732d18f5e1"
    assert ml["test_was_not_opened"] is True and tt["test_decision_tuning"] is False
    assert sm["global_holdouts"] == {"test": ["2604.01323", "2603.18656"], "valid": ["2604.00125", "2604.03553"]}
    with (CONFIG / "global5_publication_split.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 18_523 and len({r["arxiv_id"] for r in rows}) == 18_523
    assert sum(r["partition"] == "test" for r in rows) == 2
    assert sum(r["partition"] == "valid" for r in rows) == 2
    assert sum(r["partition"] == "train" for r in rows) == 18_519


def test_test_four_methods_are_identical_but_not_reinterpreted_as_accuracy():
    test = json.loads((RESULTS / "global5_test_metrics.json").read_text(encoding="utf-8"))
    values = [test["by_method"][m]["mrr_at_5_all"] for m in ["B1", "B2", "LR13", "LGBM13"]]
    assert values == pytest.approx([53 / 59] * 4)
    assert test["by_method"]["LR13"]["gt_null_queries"] == 6
    assert test["per_source_publication"]["manual"]["queries"] == 25
    assert test["per_source_publication"]["auto"]["queries"] == 34
