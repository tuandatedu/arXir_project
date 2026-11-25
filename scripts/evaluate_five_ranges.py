"""Read-only audit: evaluate the *already fitted Range-1 models* on 5 M3 Valid ranges.

No training, no Test use, no relabeling, no dataset mutation.
Install at scripts/evaluate_five_ranges.py within existing repo.
Example: python -m scripts.evaluate_five_ranges --valid 1 p1 --valid 2 p2 ... --valid 5 p5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import joblib
import pandas as pd
import pyarrow.parquet as pq

from scripts.run_weighted_baseline import QUERY_KEYS, evaluate_baselines
from scripts.train_logistic_regression import FEATURES, VALID_META, evaluate_lr
from scripts.train_lightgbm import evaluate_lgbm

EXPECTED_ROWS = {1: 4261, 2: 3778, 3: 4464, 4: 4878, 5: 3852}
EXPECTED_SHA256 = {
    1: "f62896841d6f3b5ebbc38ea098873eaa4daacaa34a22d5c4efc7c5cde49fd294",
    2: "2f428bd8ec0179b9cb0ecd47be05e0e0e8704b97d60e3dae5986f5154183f689",
    3: "29be87ae2920d956b4c393fc82172903cbf6e2c51240eeaf978c8ea3cff7b38f",
    4: "fe01104ad0084cad8e3b80b9e0f119ed17c52d9d4c51f8ccc3c1ecbbf7a54ecb",
    5: "f9315baf3669880940c6d1dcfc140b4da362a87472989c94967f3b264b428b12",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _parse_valid_arguments(raw: list[list[str]]) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for range_name, filename in raw:
        if not range_name.isdecimal() or int(range_name) not in EXPECTED_ROWS:
            raise ValueError("Range phải là số 1..5")
        r = int(range_name)
        if r in out:
            raise ValueError(f"Lặp range {r}")
        p = Path(filename).resolve()
        if p.name.lower() != "valid_pairs.parquet":
            raise ValueError(f"Chỉ đọc valid_pairs.parquet, không đọc Test: {p}")
        if not p.is_file():
            raise ValueError(f"Thiếu file Range {r}: {p}")
        out[r] = p
    if set(out) != set(EXPECTED_ROWS):
        raise ValueError(f"Phải cung cấp đúng đủ 5 range (hiện có: {sorted(out)})")
    if len(set(out.values())) != 5:
        raise ValueError("Mỗi Range phải có file Validation khác nhau")
    return out


def _model_snapshot(path: Path, key: str) -> tuple[object, list[str]]:
    if not path.is_file():
        raise ValueError(f"Không thấy model: {path}")
    blob = joblib.load(path)  # Chỉ mở artifact của chính nhóm bạn đã tạo, không tải model lạ.
    if not isinstance(blob, dict) or key not in blob or "features" not in blob:
        raise ValueError(f"Model artifact không đúng cấu trúc: {path}")
    if list(blob["features"]) != FEATURES or "doi_match" in FEATURES:
        raise ValueError(f"Model {path.name} không đúng bộ 13 features")
    return blob[key], blob["features"]


def _top1_lookup(baseline: dict, key: str) -> dict[tuple[str, str], str]:
    return {(q["arxiv_id"], q["citation_key"]): q[key]["top1_ref_arxiv_id"]
            for q in baseline["queries"]}


def _top1_model(df: pd.DataFrame) -> dict[tuple[str, str], str]:
    top1 = df.loc[df["rank"].eq(1)]
    return {(str(r.arxiv_id), str(r.citation_key)): str(r.ref_arxiv_id)
            for r in top1.itertuples(index=False)}


def _agg(result_rows: list[dict], method: str) -> dict:
    total_queries = sum(r["queries"] for r in result_rows)
    pos_queries = sum(r["positive_queries"] for r in result_rows)
    total_rr = math.fsum(r[method]["mrr_at_5"] * r["queries"] for r in result_rows)
    pos_rr = math.fsum(r[method]["mrr_at_5_positive_only"] * r["positive_queries"]
                       for r in result_rows if r["positive_queries"])
    return {
        "mrr_at_5_micro_queries": total_rr / total_queries,
        "mrr_at_5_macro_ranges": math.fsum(r[method]["mrr_at_5"] for r in result_rows) / len(result_rows),
        "mrr_at_5_positive_only_micro_queries": pos_rr / pos_queries if pos_queries else None,
        "positive_top1_count": sum(r[method]["positive_top1_count"] for r in result_rows),
        "positive_queries": pos_queries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valid", nargs=2, action="append", required=True, metavar=("RANGE", "FILE"))
    parser.add_argument("--lr-model", type=Path,
                        default=Path("outputs/lr13_full_20261125_01/lr13_model.joblib"))
    parser.add_argument("--lgbm-model", type=Path,
                        default=Path("outputs/lgbm13_full_20261125_01/lgbm13_model.joblib"))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/five_range_valid_audit_01"))
    args = parser.parse_args()
    try:
        sources = _parse_valid_arguments(args.valid)
        if args.out_dir.exists():
            raise ValueError(f"Output đã tồn tại, không ghi đè: {args.out_dir}")
        lr, _ = _model_snapshot(args.lr_model, "pipeline")
        lgbm, _ = _model_snapshot(args.lgbm_model, "model")
        rows: list[dict] = []
        observed_paper_ids: set[str] = set()
        query_details: list[dict] = []
        for r, path in sorted(sources.items()):
            pqf = pq.ParquetFile(path)
            if pqf.metadata.num_rows != EXPECTED_ROWS[r]:
                raise ValueError(f"Range {r}: expected {EXPECTED_ROWS[r]} Valid pairs, got {pqf.metadata.num_rows}")
            columns = list(dict.fromkeys(FEATURES + VALID_META))
            missing = set(columns) - set(pqf.schema_arrow.names)
            if missing:
                raise ValueError(f"Range {r} thiếu cột: {sorted(missing)}")
            digest = _sha256(path)
            if digest != EXPECTED_SHA256[r]:
                raise ValueError(f"Range {r} không đúng snapshot M3 Drive đã kiểm tra")
            df = pd.read_parquet(path, columns=columns)
            pubs = set(df["arxiv_id"].astype(str).unique())
            if pubs & observed_paper_ids:
                raise ValueError(f"Source paper trùng giữa các range: {pubs & observed_paper_ids}")
            observed_paper_ids |= pubs

            b = evaluate_baselines(df)
            lr_metrics, lr_top5, _ = evaluate_lr(lr, df)
            gb_metrics, gb_top5, _ = evaluate_lgbm(lgbm, df)
            if any(x["total_queries"] != b["total_queries"] for x in (lr_metrics, gb_metrics)):
                raise AssertionError(f"Range {r}: query counts khác nhau")
            b1 = _top1_lookup(b, "title_only")
            b2 = _top1_lookup(b, "weighted")
            lr1 = _top1_model(lr_top5)
            gb1 = _top1_model(gb_top5)
            if not (set(b1) == set(b2) == set(lr1) == set(gb1)):
                raise AssertionError(f"Range {r}: query keys khác nhau")
            method_metrics = {
                "B1": b["title_only"], "B2": b["weighted"],
                "LR13": lr_metrics["lr13"], "LGBM13": gb_metrics["lgbm13"],
            }
            row = {"range": r, "valid_path": str(path), "sha256": digest,
                   "pairs": len(df), "queries": b["total_queries"],
                   "positive_queries": b["positive_queries"],
                   "null_gt_queries": b["null_gt_queries"],
                   "source_papers": len(pubs),
                   "top1_diff_LR_vs_B1": sum(lr1[k] != b1[k] for k in b1),
                   "top1_diff_LGBM_vs_B1": sum(gb1[k] != b1[k] for k in b1),
                   "top1_diff_LGBM_vs_LR": sum(gb1[k] != lr1[k] for k in b1),
                   **method_metrics}
            rows.append(row)
            for query in b["queries"]:
                key = (query["arxiv_id"], query["citation_key"])
                query_details.append({"range":r,"arxiv_id":key[0],"citation_key":key[1],
                                      "has_positive":query["has_positive"],
                                      "B1_top1":b1[key],"B2_top1":b2[key],
                                      "LR13_top1":lr1[key],"LGBM13_top1":gb1[key]})
            print(f"[RANGE {r}] pairs={row['pairs']} queries={row['queries']} "
                  f"positive={row['positive_queries']} GT-null={row['null_gt_queries']} "
                  + " ".join(f"{m}={method_metrics[m]['mrr_at_5']:.6f}" for m in ("B1","B2","LR13","LGBM13")),flush=True)
        report = {
            "protocol": "Frozen Range1 LR13 and LGBM13 models evaluated on five M3 Validation ranges",
            "evaluation_only": True, "test_set_used": False,
            "trained_on": "Range 1 TRAIN only; not 5 separate trainings / not 5-fold CV",
            "total_queries": sum(x["queries"] for x in rows),
            "total_valid_pairs": sum(x["pairs"] for x in rows),
            "methods": {m:_agg(rows,m) for m in ("B1","B2","LR13","LGBM13")},
            "ranges": rows,
            "limitations": ["Manual labels may confirm heuristic suggestions; do not assume independent blind labeling",
                            "GT-null receives RR=0 under existing rule",
                            "Do not select new hyperparameters from this external-range audit if later reporting as holdout"],
        }
        args.out_dir.mkdir(parents=True,exist_ok=False)
        (args.out_dir/"five_range_valid_metrics.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        pd.DataFrame(query_details).to_csv(args.out_dir/"five_range_top1_comparison.csv",index=False)
        pd.DataFrame([{
            "range":row["range"],"pairs":row["pairs"],"queries":row["queries"],
            "positive_queries":row["positive_queries"],"null_gt_queries":row["null_gt_queries"],
            **{f"{m}_mrr_at_5":row[m]["mrr_at_5"] for m in ("B1","B2","LR13","LGBM13")},
        } for row in rows]).to_csv(args.out_dir/"five_range_summary.csv",index=False)
        print("[AGGREGATE]",{m:report["methods"][m]["mrr_at_5_micro_queries"]
                             for m in ("B1","B2","LR13","LGBM13")})
        print("[SAVED]",args.out_dir.resolve())
        return 0
    except (OSError, ValueError, AssertionError, KeyError) as exc:
        parser.error(str(exc))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
