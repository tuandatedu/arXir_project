r"""Train LightGBM (LGBM13) on the SAME frozen M3 Range-1 data as LR13.

Drop-in destination in local repository: scripts/train_lightgbm.py
This is a pairwise binary classifier; candidates are ranked by P(label=1).
It does NOT implement the listwise LambdaMART / LGBMRanker objective.

Safety: read-only Train/Validation inputs; never uses Test; never overwrites an
existing output directory. Fixed initial hyperparameters (no Valid tuning).
No StandardScaler: a tree-based model does not require feature standardization.

Example PowerShell (run from repo root):
  .\.venv\Scripts\python.exe -m scripts.train_lightgbm --train $Train --valid $Valid \
      --out-dir .\outputs\lgbm13_check_01 --expect-train-rows 4185238 \
      --expect-valid-rows 4261 --check-only
  .\.venv\Scripts\python.exe -m scripts.train_lightgbm --train $Train --valid $Valid \
      --out-dir .\outputs\lgbm13_smoke_01 --smoke-rows 50000 \
      --expect-train-rows 4185238 --expect-valid-rows 4261
  .\.venv\Scripts\python.exe -m scripts.train_lightgbm --train $Train --valid $Valid \
      --out-dir .\outputs\lgbm13_full_01 --expect-train-rows 4185238 \
      --expect-valid-rows 4261
"""
from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from scripts.train_logistic_regression import (
    FEATURES,
    VALID_META,
    get_parquet_info,
    load_training_frame,
    sha256,
)
from scripts.run_weighted_baseline import (
    QUERY_KEYS,
    _metrics,
    evaluate_baselines,
    rank_candidates,
    validate_pairs,
)

# Fixed protocol settings; do not tune using Test.
PARAMS = {
    "boosting_type": "gbdt",
    "objective": "binary",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 100,
    "reg_lambda": 1.0,
    "class_weight": None,
    "random_state": 42,
    "deterministic": True,
    "force_col_wise": True,
    "verbosity": -1,
}


def train_lgbm(train_frame: pd.DataFrame, *, n_jobs: int = 4,
               min_child_samples: int | None = None,
               n_estimators: int | None = None):
    """Fit on Training only; return fitted LGBMClassifier and class counts."""
    if train_frame.empty:
        raise ValueError("Training rỗng")
    X = train_frame[FEATURES].to_numpy(dtype=np.float32, copy=True)
    if not np.isfinite(X).all():
        raise ValueError("Training chứa NaN hoặc Inf")
    y = train_frame["label"].to_numpy()
    if not np.isin(y, [0, 1]).all() or set(np.unique(y).tolist()) != {0, 1}:
        raise ValueError("Training phải có đúng hai nhãn 0/1")
    y = y.astype(np.int8, copy=False)
    cfg = dict(PARAMS)
    cfg["n_jobs"] = n_jobs
    if min_child_samples is not None:
        cfg["min_child_samples"] = min_child_samples
    if n_estimators is not None:
        cfg["n_estimators"] = n_estimators
    model = lgb.LGBMClassifier(**cfg)
    model.fit(X, y, feature_name=FEATURES)
    counts = np.bincount(y, minlength=2)
    stats = {
        "pairs": int(len(y)),
        "negative_pairs": int(counts[0]),
        "positive_pairs": int(counts[1]),
        "positive_fraction": float(counts[1] / len(y)),
    }
    return model, stats


def evaluate_lgbm(model: lgb.LGBMClassifier, frame: pd.DataFrame):
    """Exactly B1/B2's query grouping, tie break and all/positive-only MRR@5."""
    validate_pairs(frame)
    X = frame[FEATURES].to_numpy(dtype=np.float32, copy=True)
    if not np.isfinite(X).all():
        raise ValueError("Validation chứa NaN hoặc Inf")
    classes = list(model.classes_)
    if 1 not in classes:
        raise ValueError("Model không có class 1")
    scored = frame.copy()
    scored["score"] = model.predict_proba(pd.DataFrame(X, columns=FEATURES))[:, classes.index(1)]
    if not np.isfinite(scored["score"].to_numpy()).all():
        raise ValueError("Validation predict_proba chứa NaN hoặc Inf")

    baseline = evaluate_baselines(frame)
    records, top5_rows, query_rows = [], [], []
    for (paper_id, citation_key), group in scored.groupby(QUERY_KEYS, sort=True):
        ranked = rank_candidates(group, "score")
        has_positive = bool(group["label"].eq(1).any())
        positive_positions = np.flatnonzero(ranked["label"].to_numpy() == 1)
        full_rank = int(positive_positions[0]) + 1 if len(positive_positions) else None
        rank_at_5 = full_rank if full_rank is not None and full_rank <= 5 else None
        rr = 1.0 / rank_at_5 if rank_at_5 is not None else 0.0
        records.append({"arxiv_id": paper_id,
                        "citation_key": citation_key,
                        "has_positive": has_positive,
                        "lgbm": {"positive_rank_full": full_rank,
                                 "correct_rank_at_5": rank_at_5,
                                 "rr_at_5": rr}})
        query_rows.append({"arxiv_id": paper_id, "citation_key": citation_key,
                           "has_positive": has_positive,
                           "positive_rank_full": full_rank, "rr_at_5": rr,
                           "candidate_count": int(len(group))})
        for rank, (_, row) in enumerate(ranked.head(5).iterrows(), start=1):
            top5_rows.append({"arxiv_id": paper_id, "citation_key": citation_key,
                              "rank": rank, "ref_arxiv_id": row["ref_arxiv_id"],
                              "score": float(row["score"]), "label": int(row["label"])})

    if len(records) != baseline["total_queries"]:
        raise AssertionError("B1/B2 và LightGBM có số query Validation khác nhau")
    metrics = {
        "total_pairs": int(len(frame)),
        "total_queries": int(len(records)),
        "positive_queries": int(sum(q["has_positive"] for q in records)),
        "null_gt_queries": baseline["null_gt_queries"],
        "known_gt_without_positive_queries": baseline["known_gt_without_positive_queries"],
        "lgbm13": _metrics(records, "lgbm"),
        "baseline_1_title_only": baseline["title_only"],
        "baseline_2_weighted": baseline["weighted"],
        "note": "MRR@5(all): RR=0 for GT-null; positive-only shown separately. No Test used.",
    }
    return metrics, pd.DataFrame(top5_rows), pd.DataFrame(query_rows)


def feature_importance_frame(model: lgb.LGBMClassifier) -> pd.DataFrame:
    booster = model.booster_
    importance = pd.DataFrame({
        "feature": FEATURES,
        "importance_gain": booster.feature_importance(importance_type="gain"),
        "importance_split": booster.feature_importance(importance_type="split"),
    })
    importance["gain_fraction"] = (
        importance["importance_gain"] / importance["importance_gain"].sum()
        if importance["importance_gain"].sum() > 0 else 0.0
    )
    return importance.sort_values("importance_gain", ascending=False, kind="mergesort")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--valid", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path, help="Thư mục mới, chưa tồn tại")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--smoke-rows", type=int, default=None,
                        help="Chỉ train thử N dòng đầu; KHÔNG phải kết quả chính thức")
    parser.add_argument("--expect-train-rows", type=int, default=None)
    parser.add_argument("--expect-valid-rows", type=int, default=None)
    parser.add_argument("--num-threads", type=int, default=4,
                        help="Số CPU threads; mặc định 4")
    args = parser.parse_args(argv)
    if args.num_threads < 1:
        parser.error("--num-threads phải >= 1")
    if args.smoke_rows is not None and args.smoke_rows <= 0:
        parser.error("--smoke-rows phải > 0")
    if args.train.resolve() == args.valid.resolve():
        parser.error("Train và Validation phải khác nhau")
    if args.out_dir.exists():
        parser.error(f"Output đã tồn tại: {args.out_dir}; chọn tên mới, không ghi đè")
    if "test" in args.train.name.lower() or "test" in args.valid.name.lower():
        parser.error("Không được dùng Test set")

    try:
        train_meta = get_parquet_info(args.train, FEATURES + ["label"], args.expect_train_rows)
        valid_meta = get_parquet_info(args.valid, FEATURES + VALID_META, args.expect_valid_rows)
        print("[CHECK] Train:", train_meta["path"], "rows:", train_meta["num_rows"], flush=True)
        print("[CHECK] Valid:", valid_meta["path"], "rows:", valid_meta["num_rows"], flush=True)
        print("[CHECK] Feature set: LGBM13, no doi_match, no StandardScaler", flush=True)
        if args.check_only:
            print("CHECK ONLY PASSED. Chưa train và chưa tạo output.")
            return 0

        train_df = load_training_frame(args.train, args.smoke_rows)
        model, train_stats = train_lgbm(train_df, n_jobs=args.num_threads)
        del train_df
        valid_df = pd.read_parquet(args.valid, columns=FEATURES + VALID_META)
        valid_report, top5_df, queries_df = evaluate_lgbm(model, valid_df)
        del valid_df

        importance = feature_importance_frame(model)
        report = {
            "protocol": "M3 Range 1 | LGBM13 | same 13 features and Validation as LR13/B1/B2",
            "run_type": "SMOKE_ONLY_NOT_FINAL" if args.smoke_rows is not None else "FULL_TRAINING",
            "model": {"type": "LGBMClassifier (binary, pairwise)",
                      "lightgbm_version": lgb.__version__,
                      "python_version": platform.python_version(),
                      "params": model.get_params(),
                      "actual_trees": int(model.n_estimators_)},
            "features": FEATURES,
            "data": {
                "train": {"path": train_meta["path"], "rows": train_meta["num_rows"],
                          "sha256": sha256(args.train)},
                "valid": {"path": valid_meta["path"], "rows": valid_meta["num_rows"],
                          "sha256": sha256(args.valid)},
            },
            "train": train_stats,
            "validation": valid_report,
            "limitations": ["automatic Ground Truth uses DOI-first hybrid (also Title/Author/Year)",
                            "Validation has GT-null queries with RR=0",
                            "Validation contains only two source publications",
                            "This is a binary classifier, not a LambdaMART ranker",
                            "Test set not used"],
        }
        args.out_dir.mkdir(parents=True, exist_ok=False)
        joblib.dump({"model": model, "features": FEATURES},
                    args.out_dir / "lgbm13_model.joblib")
        (args.out_dir / "metrics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        importance.to_csv(args.out_dir / "feature_importance.csv", index=False)
        top5_df.to_csv(args.out_dir / "validation_top5.csv", index=False)
        queries_df.to_csv(args.out_dir / "validation_queries.csv", index=False)
        print("[RUN TYPE]", report["run_type"])
        print("[TRAIN]", train_stats)
        print("[VALID]", {k: v for k, v in valid_report.items() if k != "note"})
        print("[SAVED]", args.out_dir.resolve())
        return 0
    except (ValueError, OSError, ImportError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
