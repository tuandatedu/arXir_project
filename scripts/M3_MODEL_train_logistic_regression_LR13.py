"""Logistic Regression (13 no-DOI features) for the frozen M3 Range-1 snapshot.

REPLACEMENT for scripts/train_logistic_regression.py on GitHub branch M3-model.
Keeps the existing StandardScaler + LogisticRegression approach, while reusing
Baseline 2's validation, ranking and metric implementation.

This script NEVER edits M1/M2/M3 inputs or Test; outputs only to a NEW directory.

Examples (PowerShell, from repository root):
  python -m scripts.train_logistic_regression --train ...train_pairs.parquet \
      --valid ...valid_pairs.parquet --out-dir outputs/lr13_check --check-only
  python -m scripts.train_logistic_regression --train ...train_pairs.parquet \
      --valid ...valid_pairs.parquet --out-dir outputs/lr13_smoke_001 --smoke-rows 50000
  python -m scripts.train_logistic_regression --train ...train_pairs.parquet \
      --valid ...valid_pairs.parquet --out-dir outputs/lr13_full_001 \
      --expect-train-rows 4185238 --expect-valid-rows 4261
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.run_weighted_baseline import (
    QUERY_KEYS,
    _metrics,
    evaluate_baselines,
    rank_candidates,
    validate_pairs,
)

FEATURES = [
    "title_levenshtein",
    "title_token_sort",
    "title_token_set",
    "title_jaccard",
    "title_exact",
    "title_len_diff_ratio",
    "author_jaccard",
    "author_first_match",
    "author_any_match",
    "year_diff",
    "year_exact",
    "year_missing",
    "cite_count",
]
VALID_META = ["arxiv_id", "citation_key", "ref_arxiv_id", "groundtruth_arxiv_id", "label"]


def get_parquet_info(path: Path, required: list[str], expected_rows: int | None) -> dict:
    if not path.is_file():
        raise ValueError(f"Không tìm thấy Parquet: {path}")
    parquet = pq.ParquetFile(path)
    columns = parquet.schema_arrow.names
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValueError(f"{path.name} thiếu cột: {missing}")
    count = parquet.metadata.num_rows
    if expected_rows is not None and count != expected_rows:
        raise ValueError(f"{path.name}: expected {expected_rows} rows, found {count}")
    return {"path": str(path.resolve()), "num_rows": count, "columns": columns}


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_training_frame(path: Path, smoke_rows: int | None) -> pd.DataFrame:
    if smoke_rows is None:
        return pd.read_parquet(path, columns=FEATURES + ["label"])
    if smoke_rows <= 0:
        raise ValueError("--smoke-rows phải > 0")
    batches = []
    remaining = smoke_rows
    for batch in pq.ParquetFile(path).iter_batches(batch_size=10000, columns=FEATURES + ["label"]):
        part = batch.to_pandas()
        batches.append(part.iloc[:remaining].copy())
        remaining -= min(remaining, len(part))
        if remaining <= 0:
            break
    if not batches:
        raise ValueError("Training rỗng")
    return pd.concat(batches, ignore_index=True)


def train_lr(train_frame: pd.DataFrame):
    if train_frame.empty:
        raise ValueError("Training rỗng")
    X = train_frame[FEATURES].to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(X).all():
        raise ValueError("Training chứa NaN hoặc Inf")
    y = train_frame["label"].to_numpy()
    if not np.isin(y, [0, 1]).all() or set(np.unique(y).tolist()) != {0, 1}:
        raise ValueError("Train phải chứa hai nhãn 0/1 hợp lệ")
    y = y.astype(np.int8, copy=False)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            class_weight=None, solver="lbfgs", max_iter=1000, random_state=42
        ),
    )
    model.fit(X, y)
    counts = np.bincount(y, minlength=2)
    return model, {"pairs": len(y), "negative_pairs": int(counts[0]),
                   "positive_pairs": int(counts[1]),
                   "positive_fraction": float(counts[1] / len(y))}


def evaluate_lr(model, frame: pd.DataFrame):
    """Use precisely the same query grouping, tie-breaking and _metrics as B1/B2."""
    validate_pairs(frame)
    x_valid = frame[FEATURES].to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(x_valid).all():
        raise ValueError("Validation chứa NaN hoặc Inf")
    model_lr = model.named_steps["logisticregression"]
    positive_index = list(model_lr.classes_).index(1)
    scored = frame.copy()
    scored["score"] = model.predict_proba(x_valid)[:, positive_index]
    if not np.isfinite(scored["score"].to_numpy()).all():
        raise ValueError("Validation predict_proba chứa NaN hoặc Inf")

    baseline_report = evaluate_baselines(frame)  # B1/B2 on precisely the SAME frame
    queries, top5_rows, query_rows = [], [], []
    for (paper_id, citation_key), group in scored.groupby(QUERY_KEYS, sort=True):
        ranked = rank_candidates(group, "score")
        has_pos = bool(group["label"].eq(1).any())
        positive_positions = np.flatnonzero(ranked["label"].to_numpy() == 1)
        full_rank = int(positive_positions[0]) + 1 if len(positive_positions) else None
        top5_rank = full_rank if full_rank is not None and full_rank <= 5 else None
        rr = (1.0 / top5_rank) if top5_rank is not None else 0.0
        query_record = {
            "arxiv_id": paper_id,
            "citation_key": citation_key,
            "has_positive": has_pos,
            "lr": {"positive_rank_full": full_rank,
                   "correct_rank_at_5": top5_rank, "rr_at_5": rr},
        }
        queries.append(query_record)
        query_rows.append({"arxiv_id": paper_id, "citation_key": citation_key,
                           "has_positive": has_pos, "positive_rank_full": full_rank,
                           "rr_at_5": rr, "candidate_count": len(group)})
        for rank, (_, row) in enumerate(ranked.head(5).iterrows(), start=1):
            top5_rows.append({"arxiv_id": paper_id, "citation_key": citation_key,
                              "rank": rank, "ref_arxiv_id": row["ref_arxiv_id"],
                              "score": float(row["score"]), "label": int(row["label"])})
    if len(queries) != baseline_report["total_queries"]:
        raise AssertionError("B1/B2 and LR use different validation query counts")

    # _metrics is from the already tested run_weighted_baseline.py.
    lr_metrics = _metrics(queries, "lr")
    return {
        "total_pairs": int(len(frame)),
        "total_queries": int(len(queries)),
        "positive_queries": int(sum(q["has_positive"] for q in queries)),
        "null_gt_queries": baseline_report["null_gt_queries"],
        "known_gt_without_positive_queries": baseline_report["known_gt_without_positive_queries"],
        "lr13": lr_metrics,
        "baseline_1_title_only": baseline_report["title_only"],
        "baseline_2_weighted": baseline_report["weighted"],
        "note": "MRR@5(all) assigns RR=0 for queries without a positive pair; positive-only metrics reported separately.",
    }, pd.DataFrame(top5_rows), pd.DataFrame(query_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, type=Path, help="Explicit train Parquet path")
    parser.add_argument("--valid", required=True, type=Path, help="Explicit validation Parquet path")
    parser.add_argument("--out-dir", required=True, type=Path, help="NEW, nonexistent output directory")
    parser.add_argument("--check-only", action="store_true", help="Read metadata only; do not train or create files")
    parser.add_argument("--smoke-rows", type=int, default=None, help="Fit on first N Train rows ONLY for a mechanical smoke test; never report as final")
    parser.add_argument("--expect-train-rows", type=int, default=None)
    parser.add_argument("--expect-valid-rows", type=int, default=None)
    args = parser.parse_args(argv)

    train_path, valid_path = args.train, args.valid
    if train_path.resolve() == valid_path.resolve():
        parser.error("Train và Validation không được cùng một file")
    if args.out_dir.exists():
        parser.error(f"Output directory đã tồn tại: {args.out_dir}. Chọn tên mới để không ghi đè!")
    if "test" in train_path.name.lower() or "test" in valid_path.name.lower():
        parser.error("Không được dùng Test set cho training/validation")
    try:
        info_train = get_parquet_info(train_path, FEATURES + ["label"], args.expect_train_rows)
        info_valid = get_parquet_info(valid_path, FEATURES + VALID_META, args.expect_valid_rows)
        print("[CHECK] Train:", info_train["path"], "rows:", info_train["num_rows"])
        print("[CHECK] Valid:", info_valid["path"], "rows:", info_valid["num_rows"])
        print("[CHECK] Feature set: LR13, no doi_match")
        if args.check_only:
            print("CHECK ONLY PASSED. Chưa train và chưa tạo output.")
            return 0

        train_df = load_training_frame(train_path, args.smoke_rows)
        model, train_metrics = train_lr(train_df)
        del train_df
        valid_df = pd.read_parquet(valid_path, columns=FEATURES + VALID_META)
        metrics, top5_df, queries_df = evaluate_lr(model, valid_df)
        del valid_df

        lr = model.named_steps["logisticregression"]
        coef_df = pd.DataFrame({"feature": FEATURES, "coefficient": lr.coef_[0]})
        coef_df["abs_coefficient"] = coef_df["coefficient"].abs()
        coef_df = coef_df.sort_values("abs_coefficient", ascending=False, kind="mergesort")

        report = {
            "protocol": "M3 Range 1 | LR13 | B1/B2 comparison on same Validation",
            "run_type": "SMOKE_ONLY_NOT_FINAL" if args.smoke_rows is not None else "FULL_TRAINING",
            "model": {"pipeline": "StandardScaler + LogisticRegression",
                      "solver": "lbfgs", "max_iter": 1000, "random_state": 42,
                      "class_weight": None, "n_iter": int(lr.n_iter_[0]),
                      "intercept": float(lr.intercept_[0])},
            "features": FEATURES,
            "data": {"train": {"path": info_train["path"], "rows": info_train["num_rows"], "sha256": sha256(train_path)},
                     "valid": {"path": info_valid["path"], "rows": info_valid["num_rows"], "sha256": sha256(valid_path)}},
            "train": train_metrics,
            "validation": metrics,
            "limitations": ["automatic labels use DOI-first hybrid (also title/author/year)",
                            "Validation has GT-null queries with RR=0", "Test set not used"],
        }
        args.out_dir.mkdir(parents=True, exist_ok=False)
        joblib.dump({"pipeline": model, "features": FEATURES}, args.out_dir / "lr13_model.joblib")
        (args.out_dir / "metrics.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        coef_df.to_csv(args.out_dir / "coefficients.csv", index=False)
        top5_df.to_csv(args.out_dir / "validation_top5.csv", index=False)
        queries_df.to_csv(args.out_dir / "validation_queries.csv", index=False)
        print("[RUN TYPE]", report["run_type"])
        print("[TRAIN]", train_metrics)
        print("[VALID]", {k: v for k, v in metrics.items() if k != "note"})
        print("[SAVED]", args.out_dir.resolve())
        return 0
    except (ValueError, OSError, ImportError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
