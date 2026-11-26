#!/usr/bin/env python3
r"""One-time frozen M3 Range-1 Test evaluation (read-only inputs).

Run ONLY after a successful Step 4.6 local preflight. It verifies the saved
lock and both *trusted local* .joblib model checksums BEFORE reading Test.
It does not fit, tune, re-label or change input files. It writes reports to
an entirely NEW output directory.

From Windows PowerShell at the project root:
    python .\M3_STEP4_7_RUN_TEST_READONLY.py `
      --repo . `
      --lock .\outputs\step46_local_verify_20261125_01\verified_protocol_lock.json `
      --out-dir .\outputs\step47_test_r1_20261125_01

IMPORTANT: .joblib uses Python pickle; ONLY load models you generated yourself.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

COMMIT = "7f542abd88f4864b58bbca3fe183a0a4b7e7628b"
PROTOCOL_ID = "IntroDS_M3_R1_LR13_PreTest_2026-11-25_v1"
FEATURES = [
    "title_levenshtein", "title_token_sort", "title_token_set", "title_jaccard",
    "title_exact", "title_len_diff_ratio", "author_jaccard", "author_first_match",
    "author_any_match", "year_diff", "year_exact", "year_missing", "cite_count",
]
META = ["arxiv_id", "citation_key", "ref_arxiv_id", "groundtruth_arxiv_id", "label"]
QUERY_KEYS = ["arxiv_id", "citation_key"]
METHODS = ["B1", "B2", "LR13", "LGBM13"]
EXPECTED_TRAIN_SHA = "f9cf5eb22ad1aad07b2db3135c26802cf00cd06fffc9e183dbaa3275c7dec27f"
EXPECTED_VALID_SHA = "f62896841d6f3b5ebbc38ea098873eaa4daacaa34a22d5c4efc7c5cde49fd294"
# These five file names were checked in the frozen Range-1 labels/manual Drive folder.
MANUAL_PUBLICATIONS_R1 = frozenset({
    "2610.01282", "2609.39989", "2610.02014", "2610.00928", "2610.01936"
})
# Drive metadata for frozen Range-1 prepared_dataset/test_pairs.parquet (25 Nov 2026).
EXPECTED_TEST_BYTES = 125000
DEFAULT_TEST_REL = Path("data/m3/range_1_frozen_20261123/prepared_dataset/test_pairs.parquet")


def checked(cond: Any, description: str) -> None:
    if not cond:
        raise ValueError(description)
    print(f"[PASS] {description}", flush=True)


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(part)
    return hasher.hexdigest()


def git_blob_sha(path: Path, normalize_crlf: bool = False) -> str:
    raw = path.read_bytes()
    if normalize_crlf:
        raw = raw.replace(b"\r\n", b"\n")
    prefix = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(prefix + raw).hexdigest()


def json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def immutable_gate(repo: Path, lockfile: Path, test_file: Path, outdir: Path) -> tuple[dict, dict]:
    """All validation here MUST run before touching Test data."""
    checked(repo.is_dir(), "Project repository exists")
    checked(lockfile.is_file(), "Verified local protocol lock exists")
    checked(not outdir.exists(), "Output directory is new (no overwrite)")
    checked(not outdir.is_relative_to(test_file.parent), "Output directory outside frozen Test directory")
    lock = json_read(lockfile)
    checked(lock.get("protocol_id") == PROTOCOL_ID, "Correct frozen protocol ID")
    checked(lock.get("github", {}).get("commit_sha") == COMMIT, "Git commit is locked")
    checked(lock.get("selected_model", {}).get("name") == "LR13", "Primary model remains LR13")
    checked(lock.get("features") == FEATURES, "Exact 13-feature order locked")
    checked(lock.get("training_r1", {}).get("sha256") == EXPECTED_TRAIN_SHA,
            "Frozen Train SHA-256 pinned")
    checked(lock.get("validation_r1", {}).get("sha256") == EXPECTED_VALID_SHA,
            "Frozen Valid SHA-256 pinned")
    checked(lock.get("scoring", {}).get("positive_class") == 1, "Positive scoring class = 1")
    checked(lock.get("scoring", {}).get("top_k") == 5, "Top-K is 5")
    checked(lock.get("scoring", {}).get("tie_break") == "candidate_original_row_order",
            "Original row order tie-break frozen")
    checked(lock.get("scoring", {}).get("abstention") == "none", "No abstention rule")
    checked(lock.get("evaluation", {}).get("gt_null_rr") == 0,
            "GT-null receives RR=0 under frozen protocol")
    checked(lock.get("verification", {}).get("result") == "PASS",
            "Step 4.6 preflight verification=PASS")
    checked(lock.get("status", "").startswith("VERIFIED_LOCAL_PREFLIGHT_NO_TEST"),
            "Step 4.6 verified status; no previous Test run recorded in this lock")
    checked(lock.get("evaluation", {}).get("test_opened") is False,
            "Frozen configuration says Test unopened when locked")
    tr_path = (repo / lock["training_r1"]["path_relative"]).resolve()
    va_path = (repo / lock["validation_r1"]["path_relative"]).resolve()
    checked(tr_path.is_file() and sha256(tr_path) == EXPECTED_TRAIN_SHA,
            "Current frozen Range1 Train file unchanged since Step 4.6")
    checked(va_path.is_file() and sha256(va_path) == EXPECTED_VALID_SHA,
            "Current frozen Range1 Validation file unchanged since Step 4.6")
    for rel, expected_blob in lock["github"]["source_git_blob_shas"].items():
        src = repo / rel
        checked(src.is_file() and (
                git_blob_sha(src) == expected_blob or
                git_blob_sha(src, normalize_crlf=True) == expected_blob
            ), f"Source code unchanged: {rel}")
    model_specs = [
        ("LR13", "pipeline", repo / lock["selected_model"]["artifact_relative_path"],
         lock["selected_model"]["model_sha256"]),
        ("LGBM13", "model", repo / "outputs/lgbm13_full_20261125_01/lgbm13_model.joblib",
         next(c["model_sha256"] for c in lock["comparators"] if c["name"] == "LGBM13")),
    ]
    models = {}
    for name, key, model_path, expected_sha in model_specs:
        checked(model_path.is_file(), f"{name} local model available")
        checked(isinstance(expected_sha, str) and len(expected_sha) == 64,
                f"{name} SHA-256 present in verified lock")
        checked(sha256(model_path) == expected_sha,
                f"{name} model checksum unchanged since Step 4.6")
        # Trust only user-generated local artifacts; pickle/joblib are unsafe from untrusted origins.
        blob = joblib.load(model_path)
        checked(isinstance(blob, dict) and blob.get("features") == FEATURES and key in blob,
                f"{name} saved feature order / artifact structure verified")
        model = blob[key]
        if name == "LR13":
            checked(isinstance(model, Pipeline) and len(model.steps) == 2
                    and isinstance(model.steps[0][1], StandardScaler)
                    and isinstance(model.steps[1][1], LogisticRegression),
                    "LR13 type: StandardScaler -> LogisticRegression")
        else:
            from lightgbm import LGBMClassifier
            checked(isinstance(model, LGBMClassifier), "LGBM13 type: LGBMClassifier")
        checked(list(model.classes_) == [0, 1], f"{name} trained on classes [0,1]")
        models[name] = model
    checked(test_file == (repo / DEFAULT_TEST_REL).resolve(),
            "Test path matches the frozen Range-1 prepared_dataset")
    checked(test_file.is_file(), "Frozen Test Parquet file exists")
    checked(test_file.stat().st_size == EXPECTED_TEST_BYTES,
            f"Test file size matches frozen Drive metadata ({EXPECTED_TEST_BYTES} bytes)")
    checked(test_file != (repo / lock["training_r1"]["path_relative"]).resolve(),
            "Test is not Train")
    checked(test_file != (repo / lock["validation_r1"]["path_relative"]).resolve(),
            "Test is not Validation")
    return lock, models


def validate_test_frame(data: pd.DataFrame) -> dict[str, str]:
    """Check correctness of the frozen publication-scoped candidate matrix."""
    checked(not data.empty, "Test has at least one candidate pair")
    checked(data[FEATURES].notna().all().all(), "Test feature columns contain no null")
    checked(np.isfinite(data[FEATURES].to_numpy(dtype=np.float64)).all(),
            "Test features finite")
    checked(data["label"].isin([0, 1]).all(), "Test label values only 0/1")
    checked(data[QUERY_KEYS + ["ref_arxiv_id"]].notna().all().all(),
            "Test query/candidate keys non-null")
    checked(not data.duplicated(QUERY_KEYS + ["ref_arxiv_id"]).any(),
            "No duplicate reference ID within a Test query")
    pubs = sorted(set(data["arxiv_id"].astype(str)))
    checked(len(pubs) == 2, "Test contains exactly two citing publications")
    manual = sorted(set(pubs) & MANUAL_PUBLICATIONS_R1)
    auto = sorted(set(pubs) - MANUAL_PUBLICATIONS_R1)
    checked(len(manual) == len(auto) == 1,
            "Test contains exactly one verified manual and one automatic citing publication")
    source_type = {manual[0]: "manual", auto[0]: "auto"}
    for (paper, key), group in data.groupby(QUERY_KEYS, sort=False, dropna=False):
        gt_values = group["groundtruth_arxiv_id"].unique()
        if len(gt_values) != 1 and not group["groundtruth_arxiv_id"].isna().all():
            raise ValueError(f"Inconsistent GT for {(paper,key)}")
        gt = group["groundtruth_arxiv_id"].iloc[0]
        matches = (group["ref_arxiv_id"] == gt).to_numpy() if pd.notna(gt) else np.zeros(len(group), dtype=bool)
        labels = group["label"].to_numpy(dtype=np.int8)
        if not np.array_equal(labels, matches.astype(np.int8)):
            raise ValueError(f"GT and pair labels inconsistent for {(paper,key)}")
        if labels.sum() > 1:
            raise ValueError(f"More than one positive reference for {(paper,key)}")
        if pd.notna(gt) and labels.sum() != 1:
            raise ValueError(f"Known GT outside Test candidate pool for {(paper,key)}")
    for paper, pframe in data.groupby("arxiv_id", sort=False):
        candidates_sets = [frozenset(g["ref_arxiv_id"]) for _, g in pframe.groupby("citation_key", sort=False)]
        checked(len(set(candidates_sets)) == 1,
                f"Full m×n candidate matrix per Test citing paper {paper}")
    return source_type


def score_models(frame: pd.DataFrame, models: dict) -> dict[str, np.ndarray]:
    """Score using features ONLY; no Ground Truth or label reaches model inference."""
    scores = {
        "B1": frame["title_levenshtein"].to_numpy(dtype=np.float64, copy=True),
        "B2": (0.7 * frame["title_levenshtein"].to_numpy(dtype=np.float64)
               + 0.2 * frame["author_jaccard"].to_numpy(dtype=np.float64)
               + 0.1 * frame["year_exact"].to_numpy(dtype=np.float64)),
    }
    x_lr = frame[FEATURES].to_numpy(dtype=np.float64, copy=True)
    x_gbm = frame[FEATURES].to_numpy(dtype=np.float32, copy=True)
    scores["LR13"] = models["LR13"].predict_proba(x_lr)[:, 1]
    scores["LGBM13"] = models["LGBM13"].predict_proba(
        pd.DataFrame(x_gbm, columns=FEATURES)
    )[:, 1]
    for method, values in scores.items():
        checked(len(values) == len(frame) and np.isfinite(values).all(),
                f"{method} scored all candidate pairs; no NaN/Inf")
        if method != "B2":
            checked(((values >= 0) & (values <= 1)).all(),
                    f"{method} scores in [0,1]")
    return scores


def topk_and_reciprocal_rank(
    frame: pd.DataFrame, scores: dict[str, np.ndarray], source_type: dict[str, str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Exactly rank by score descending, original row order for ties, Top-5.

    GT and label are read ONLY when evaluating, after scores are fully generated.
    """
    detailed: list[dict] = []
    top5: list[dict] = []
    partial_predictions: list[dict] = []
    with_scores = frame.copy()
    for method in METHODS:
        with_scores[f"__score_{method}"] = scores[method]
    for (paper, key), group in with_scores.groupby(QUERY_KEYS, sort=True):
        gt_raw = group["groundtruth_arxiv_id"].iloc[0]
        gt = None if pd.isna(gt_raw) else str(gt_raw)
        source = source_type[str(paper)]
        has_positive = bool(group["label"].eq(1).any())
        prediction_row = {"arxiv_id": str(paper), "partition": "test", "citation_key": str(key),
                          "groundtruth_arxiv_id": gt,
                          "cand_1": None, "cand_2": None, "cand_3": None,
                          "cand_4": None, "cand_5": None}
        for method in METHODS:
            ranked = group.assign(__tie_order=np.arange(len(group))).sort_values(
                [f"__score_{method}", "__tie_order"], ascending=[False, True], kind="mergesort"
            )
            positions = np.flatnonzero(ranked["label"].to_numpy(dtype=np.int8) == 1)
            full_rank = int(positions[0] + 1) if len(positions) else None
            top5_rank = full_rank if full_rank is not None and full_rank <= 5 else None
            rr = (1.0 / top5_rank) if top5_rank is not None else 0.0
            detailed.append({
                "arxiv_id": str(paper), "source": source, "citation_key": str(key),
                "method": method, "groundtruth_arxiv_id": gt,
                "has_positive": has_positive, "candidate_count": int(len(group)),
                "positive_rank_full": full_rank, "positive_rank_top5": top5_rank,
                "rr_at_5": rr, "top1_ref_arxiv_id": str(ranked.iloc[0]["ref_arxiv_id"]),
            })
            for i, (_, candidate) in enumerate(ranked.head(5).iterrows(), 1):
                ref_id = str(candidate["ref_arxiv_id"])
                top5.append({
                    "arxiv_id": str(paper), "source": source, "citation_key": str(key),
                    "method": method, "rank": i, "ref_arxiv_id": ref_id,
                    "score": float(candidate[f"__score_{method}"]),
                    "groundtruth_arxiv_id": gt, "label": int(candidate["label"]),
                })
                if method == "LR13":
                    prediction_row[f"cand_{i}"] = ref_id
        partial_predictions.append(prediction_row)
    return detailed, top5, partial_predictions


def aggregate_metrics(detailed: list[dict], source_type: dict[str, str]) -> dict:
    rows = pd.DataFrame(detailed)
    out: dict = {
        "protocol": PROTOCOL_ID,
        "official_primary": "LR13",
        "source_publication_types": source_type,
        "per_publication": [], "per_method": {},
        "notes": [
            "GT-null query gets RR=0; no abstention / no-match classifier",
            "A null GT is not independently verified proof that no matching paper exists",
            "All four approaches evaluated after fixed model/protocol selection; no Test tuning",
            "LR13 and LightGBM are pairwise binary classifiers used to rank candidates, not LambdaMART",
            "Individual Range1 Test evaluation; not yet the full final dataset predictions export",
        ],
    }
    for method in METHODS:
        subset = rows[rows.method == method]
        out["per_method"][method] = summarize_subset(subset)
        for paper, pub_rows in subset.groupby("arxiv_id", sort=True):
            record = {"method": method, "arxiv_id": str(paper), "source": source_type[str(paper)]}
            record.update(summarize_subset(pub_rows))
            out["per_publication"].append(record)
    # Optional descriptive macro average of the two source publications per method.
    out["descriptive_macro_publications"] = {
        m: float(np.mean([x["mrr_at_5_all_queries"] for x in out["per_publication"]
                          if x["method"] == m])) for m in METHODS
    }
    return out


def summarize_subset(rows: pd.DataFrame) -> dict:
    n = len(rows)
    positives = rows[rows["has_positive"]]
    nulls = n - len(positives)
    q_rr = rows["rr_at_5"].to_numpy(dtype=np.float64)
    p_rr = positives["rr_at_5"].to_numpy(dtype=np.float64)
    return {
        "queries": int(n), "positive_queries": int(len(positives)), "gt_null_queries": int(nulls),
        "mrr_at_5_all_queries": float(math.fsum(q_rr) / n) if n else None,
        "mrr_at_5_positive_only": float(math.fsum(p_rr) / len(positives)) if len(positives) else None,
        "hit_at_1_positive_only": (float((positives["positive_rank_full"] == 1).mean())
                                   if len(positives) else None),
        "hit_at_5_positive_only": (float(positives["positive_rank_top5"].notna().mean())
                                   if len(positives) else None),
    }


def test_summary_markdown(report: dict) -> str:
    lines = [
        "# M3 — Bước 4.7: Test Evaluation (Range 1)",
        "",
        f"- Protocol: `{PROTOCOL_ID}` (fixed before Test)",
        f"- Primary ML model: **LR13**; comparators: B1, B2, LGBM13",
        f"- Git commit: `{COMMIT}`",
        f"- Test SHA-256: `{report['provenance']['test_sha256']}`",
        "- Methodology: one BibTeX query, candidate pool within same citing publication; score descending, ties retain input order.",
        "- MRR@5: GT-null contributes RR=0; positive-only MRR / Hit@1 / Hit@5 also provided.",
        "",
        "## MRR@5 per publication (official primary + comparators)",
        "",
        "| Method | Label origin | Publication | Queries | Positive | GT-null | MRR@5 | Positive-only MRR@5 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for x in report["per_publication"]:
        p = x["mrr_at_5_positive_only"]
        pp = f"{p:.6f}" if p is not None else "n/a"
        lines.append(
            f"| {x['method']} | {x['source']} | `{x['arxiv_id']}` | {x['queries']} | "
            f"{x['positive_queries']} | {x['gt_null_queries']} | "
            f"{x['mrr_at_5_all_queries']:.6f} | {pp} |"
        )
    lines += [
        "", "## MRR@5 tổng hợp theo query (bổ sung, không thay thế hai publication)", "",
        "| Method | Queries | Positive | GT-null | Micro MRR@5 |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        x = report["per_method"][method]
        lines.append(
            f"| {method} | {x['queries']} | {x['positive_queries']} | "
            f"{x['gt_null_queries']} | {x['mrr_at_5_all_queries']:.6f} |"
        )
    lines += [
        "", "## Giới hạn diễn giải", "",
        "- `MRR@5=1` trên nhóm Positive không chứng minh mô hình chính xác trên mọi citation hoặc trên dữ liệu thực tế.",
        "- Automatic Ground Truth theo quy tắc DOI-first, title/author/year fallback; có nguy cơ label dependence.",
        "- GT-null chưa phải bằng chứng độc lập rằng ngoài thực tế không có tài liệu khớp.",
        "- 2 source publications ở Test Range1; không diễn giải như một nghiên cứu với hàng trăm independent publications.",
        "- Không chọn lại mô hình/hyperparameters dựa trên Test; đây là báo cáo cố định, không phải điểm điều chỉnh tiếp.",
        "- File `test_lr13_predictions_ONLY.csv` mới là prediction Test Range1; chưa đủ final `predictions.parquet` train/valid/test.",
    ]
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def selftest() -> None:
    """Synthetic only; no Test/data/model files, no fit necessary."""
    class FakeModel:
        def __init__(self, constant): self.constant = constant
        def predict_proba(self, X):
            n = len(X)
            ones = np.asarray([self.constant] * n, dtype=np.float64)
            return np.c_[1-ones, ones]
    def feat():
        d = {f: 0.3 for f in FEATURES}
        d.update(title_levenshtein=0.4, author_jaccard=0.8, year_exact=1.0)
        return d
    test = []
    for pub, source, cid_count in [("2610.01282", "manual", 3), ("9999.00001", "auto", 6)]:
        for i in range(cid_count):
            row = {**feat(), "arxiv_id": pub, "citation_key": "key1",
                   "ref_arxiv_id": f"ref{i}",
                   "groundtruth_arxiv_id": "ref2" if source == "manual" else None,
                   "label": int(source == "manual" and i == 2)}
            test.append(row)
    df = pd.DataFrame(test)
    # Tests GT-null zero and Top5 padding with <5 candidates.
    source = validate_test_frame(df)
    assert source == {"2610.01282": "manual", "9999.00001": "auto"}
    scores = score_models(df, {"LR13": FakeModel(.6), "LGBM13": FakeModel(.7)})
    detailed, top5, partial = topk_and_reciprocal_rank(df, scores, source)
    metrics = aggregate_metrics(detailed, source)
    assert len(detailed) == 2 * 4
    assert len(top5) == (3 + 5) * 4
    assert len(partial) == 2
    assert partial[0]["cand_4"] is None and partial[0]["cand_5"] is None
    assert partial[1]["cand_5"] == "ref4"
    assert metrics["per_method"]["LR13"]["mrr_at_5_all_queries"] == (1/3)/2
    assert metrics["per_method"]["B1"]["positive_queries"] == 1
    print("[PASS] Synthetic Step 4.7: 1 manual+1 auto, 3/6 candidate rows, GT-null,")
    print("[PASS] stable equal-score ties, Top-5 padding, method comparisons and MRR")
    print("Synthetic-only selftest PASSED; no real Test or model opened")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--test", type=Path, help="Optional path; must be frozen Range1 prepared_dataset/test_pairs.parquet")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--selftest", action="store_true", help="Synthetic; does not open real Test")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
            return 0
        if args.lock is None or args.out_dir is None:
            parser.error("--lock and --out-dir are required for official Test run")
        repo = args.repo.resolve()
        out = args.out_dir.resolve()
        test_file = args.test.resolve() if args.test else (repo / DEFAULT_TEST_REL).resolve()
        lockfile = args.lock.resolve()
        # All local hashes/protocol/model artifact gates are checked BEFORE opening Test.
        lock, models = immutable_gate(repo, lockfile, test_file, out)
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(test_file)
        checked(set(FEATURES + META).issubset(pf.schema_arrow.names),
                "Test Parquet contains all frozen feature + metadata columns")
        test_sha = sha256(test_file)
        df = pd.read_parquet(test_file, columns=FEATURES + META)
        source_type = validate_test_frame(df)
        scored = score_models(df, models)
        details, top5, only_test_predictions = topk_and_reciprocal_rank(df, scored, source_type)
        result = aggregate_metrics(details, source_type)
        result["provenance"] = {
            "source_code_commit": COMMIT,
            "step47_evaluator_sha256": sha256(Path(__file__).resolve()),
            "step46_lock_sha256": sha256(lockfile),
            "test_sha256": test_sha,
            "test_rows": int(len(df)), "test_queries": int(df.groupby(QUERY_KEYS).ngroups),
            "test_citing_publications": sorted(source_type),
            "primary_model_sha256": lock["selected_model"]["model_sha256"],
            "comparator_model_sha256": next(c["model_sha256"] for c in lock["comparators"] if c["name"]=="LGBM13"),
        }
        # Cross-check that every method yields exactly one ranking per query.
        num_q = df.groupby(QUERY_KEYS).ngroups
        checked(all(len([r for r in details if r["method"] == m]) == num_q for m in METHODS),
                "Every method produces exactly one ranking per Test query")
        checked(len(only_test_predictions) == num_q, "One LR13 Test prediction row per BibTeX entry")
        # Write output only after complete successful in-memory evaluation.
        out.mkdir(parents=True, exist_ok=False)
        (out / "test_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (out / "test_summary.md").write_text(test_summary_markdown(result), encoding="utf-8")
        write_csv(out / "test_query_metrics.csv", details)
        write_csv(out / "test_top5_comparison.csv", top5)
        write_csv(out / "test_lr13_predictions_ONLY.csv", only_test_predictions)
        # This is ONLY the Test portion; Step 4.8 must produce final 3-partition predictions.
        print("\n=== SUCCESS: STEP 4.7 TEST EVALUATION COMPLETED ===")
        for row in result["per_publication"]:
            if row["method"] == "LR13":
                print(f"[LR13 OFFICIAL] {row['source'].upper():6s} {row['arxiv_id']} | "
                      f"queries={row['queries']} positives={row['positive_queries']} "
                      f"GT-null={row['gt_null_queries']} MRR@5={row['mrr_at_5_all_queries']:.6f}")
        for method, r in result["per_method"].items():
            print(f"[{method} ALL TEST] MRR@5={r['mrr_at_5_all_queries']:.6f} | "
                  f"positives={r['positive_queries']} GT-null={r['gt_null_queries']}")
        print(f"[SAVED] {out}")
        print("[FROZEN] No refit, hyperparameter tuning, dataset mutation, or model selection from Test")
        return 0
    except (OSError, ValueError, KeyError, AssertionError, ImportError, TypeError, AttributeError) as exc:
        print(f"\n[FAILED] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No training or input modification performed. Do NOT use Test to tune the models.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
