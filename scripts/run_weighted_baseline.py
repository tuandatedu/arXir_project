"""So sánh hai heuristic cố định trên một snapshot Parquet, không huấn luyện."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype


QUERY_KEYS = ["arxiv_id", "citation_key"]
WEIGHTS = {"title_levenshtein": 0.7, "author_jaccard": 0.2, "year_exact": 0.1}
FEATURE_COLUMNS = list(WEIGHTS)
REQUIRED_COLUMNS = QUERY_KEYS + [
    "ref_arxiv_id", "groundtruth_arxiv_id", "label", *FEATURE_COLUMNS,
]
DEFAULT_DATA_PATH = "data/m3/range_1/prepared_dataset/train_dev_sample.parquet"


def _require_columns(frame: pd.DataFrame, required: list[str]) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("Thiếu cột bắt buộc: " + ", ".join(missing))


def _numeric_values(frame: pd.DataFrame, column: str) -> np.ndarray:
    series = frame[column]
    if (not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype)
            or is_complex_dtype(series.dtype)):
        raise ValueError(f"Cột {column} phải chứa số thực, không nhận chuỗi/bool/complex")
    if series.isna().any():
        raise ValueError(f"Cột {column} có giá trị thiếu hoặc NaN")
    values = series.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError(f"Cột {column} có giá trị NaN hoặc vô hạn")
    return values


def validate_features(frame: pd.DataFrame) -> None:
    """Kiểm dữ liệu đã chuẩn bị; không điền thiếu, clip hoặc chuẩn hóa lại."""
    _require_columns(frame, FEATURE_COLUMNS)
    for column in FEATURE_COLUMNS:
        values = _numeric_values(frame, column)
        if column == "year_exact":
            # -1 là sentinel thiếu năm do pipeline M3 hiện tại tạo ra.
            valid = np.isin(values, [-1.0, 0.0, 1.0])
        else:
            valid = (values >= 0.0) & (values <= 1.0)
        if not valid.all():
            raise ValueError(f"Cột {column} có giá trị ngoài miền hợp lệ")


def weighted_scores(frame: pd.DataFrame) -> np.ndarray:
    """Chỉ đọc ba feature; label và GT không tham gia tính điểm."""
    validate_features(frame)
    return (
        0.7 * frame["title_levenshtein"].to_numpy(dtype=np.float64)
        + 0.2 * frame["author_jaccard"].to_numpy(dtype=np.float64)
        + 0.1 * frame["year_exact"].to_numpy(dtype=np.float64)
    )


def validate_pairs(frame: pd.DataFrame) -> None:
    _require_columns(frame, REQUIRED_COLUMNS)
    if frame.empty:
        raise ValueError("Dataset không có candidate pairs")
    validate_features(frame)
    for column in QUERY_KEYS + ["ref_arxiv_id"]:
        if not frame[column].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
            raise ValueError(f"Cột {column} có định danh thiếu hoặc không hợp lệ")
    gt = frame["groundtruth_arxiv_id"]
    if not gt.map(lambda x: pd.isna(x) or (isinstance(x, str) and bool(x.strip()))).all():
        raise ValueError("groundtruth_arxiv_id phải là ID chuỗi hoặc null")
    labels = _numeric_values(frame, "label")
    if not np.isin(labels, [0.0, 1.0]).all():
        raise ValueError("label phải bằng 0 hoặc 1")
    if frame.duplicated(QUERY_KEYS + ["ref_arxiv_id"]).any():
        raise ValueError("Có candidate ID trùng trong cùng query")
    for key, group in frame.groupby(QUERY_KEYS, sort=True):
        if group["groundtruth_arxiv_id"].nunique(dropna=False) != 1:
            raise ValueError(f"GT không nhất quán trong query {key}")
        if group["label"].sum() > 1:
            raise ValueError(f"Query {key} có nhiều hơn một Positive")
        expected = (group["groundtruth_arxiv_id"].notna()
                    & group["ref_arxiv_id"].eq(group["groundtruth_arxiv_id"]))
        if not np.array_equal(group["label"].to_numpy(), expected.to_numpy(dtype=int)):
            raise ValueError(f"label không khớp GT/candidate trong query {key}")


def load_pairs(path: str | Path) -> pd.DataFrame:
    """Chỉ đọc tám cột cần thiết của đúng file được yêu cầu, giữ thứ tự dòng."""
    parquet = pq.ParquetFile(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in parquet.schema_arrow.names]
    if missing:
        raise ValueError("Parquet thiếu cột bắt buộc: " + ", ".join(missing))
    return parquet.read(columns=REQUIRED_COLUMNS).to_pandas()


def rank_candidates(group: pd.DataFrame, score_column: str) -> pd.DataFrame:
    """Đồng điểm: dòng xuất hiện trước thắng, giống mergesort của Baseline 1."""
    return group.assign(_tie_order=np.arange(len(group))).sort_values(
        [score_column, "_tie_order"], ascending=[False, True], kind="mergesort",
    )


def _query_result(ranked: pd.DataFrame, score_column: str) -> dict[str, Any]:
    positions = np.flatnonzero(ranked["label"].to_numpy() == 1)
    full_rank = int(positions[0]) + 1 if len(positions) else None
    rank_at_5 = full_rank if full_rank is not None and full_rank <= 5 else None
    top5 = []
    for _, row in ranked.head(5).iterrows():
        top5.append({
            "ref_arxiv_id": row["ref_arxiv_id"],
            "score": float(row[score_column]),
            "features": {f: float(row[f]) for f in FEATURE_COLUMNS},
            "label": int(row["label"]),
        })
    return {
        "positive_rank_full": full_rank,
        "correct_rank_at_5": rank_at_5,
        "rr_at_5": 1.0 / rank_at_5 if rank_at_5 is not None else 0.0,
        "top1_ref_arxiv_id": top5[0]["ref_arxiv_id"],
        "top5": top5,
    }


def _metrics(queries: list[dict[str, Any]], baseline: str) -> dict[str, Any]:
    positives = [q for q in queries if q["has_positive"]]
    n_positive = len(positives)
    top1 = sum(q[baseline]["positive_rank_full"] == 1 for q in positives)
    top5 = sum(q[baseline]["correct_rank_at_5"] is not None for q in positives)
    return {
        "mrr_at_5": math.fsum(q[baseline]["rr_at_5"] for q in queries) / len(queries),
        "mrr_at_5_positive_only": (
            math.fsum(q[baseline]["rr_at_5"] for q in positives) / n_positive
            if n_positive else None
        ),
        "hit_at_1_positive_only": top1 / n_positive if n_positive else None,
        "hit_at_5_positive_only": top5 / n_positive if n_positive else None,
        "positive_top1_count": top1,
        "positive_top5_count": top5,
    }


def evaluate_baselines(frame: pd.DataFrame) -> dict[str, Any]:
    """Cùng pairs, grouping, tie-break và metric cho hai baseline cố định."""
    validate_pairs(frame)
    scored = frame.copy()
    scored["_title_score"] = frame["title_levenshtein"].to_numpy(dtype=np.float64)
    scored["_weighted_score"] = weighted_scores(frame)
    queries = []
    for (arxiv_id, citation_key), group in scored.groupby(QUERY_KEYS, sort=True):
        raw_gt = group["groundtruth_arxiv_id"].iloc[0]
        gt = None if pd.isna(raw_gt) else raw_gt
        queries.append({
            "arxiv_id": arxiv_id,
            "citation_key": citation_key,
            "groundtruth_arxiv_id": gt,
            "has_positive": bool(group["label"].eq(1).any()),
            "candidate_pairs": len(group),
            "title_only": _query_result(rank_candidates(group, "_title_score"), "_title_score"),
            "weighted": _query_result(rank_candidates(group, "_weighted_score"), "_weighted_score"),
        })
    positives = [q for q in queries if q["has_positive"]]
    improved = sum(q["weighted"]["positive_rank_full"] < q["title_only"]["positive_rank_full"]
                   for q in positives)
    worsened = sum(q["weighted"]["positive_rank_full"] > q["title_only"]["positive_rank_full"]
                   for q in positives)
    return {
        "formula": "0.7 * title_levenshtein + 0.2 * author_jaccard + 0.1 * year_exact",
        "weights": dict(WEIGHTS),
        "tie_break": "score giảm dần, sau đó thứ tự dòng đầu vào tăng dần",
        "total_pairs": len(frame),
        "total_queries": len(queries),
        "positive_queries": len(positives),
        "null_gt_queries": sum(q["groundtruth_arxiv_id"] is None for q in queries),
        "known_gt_without_positive_queries": sum(
            q["groundtruth_arxiv_id"] is not None and not q["has_positive"] for q in queries
        ),
        "year_exact_missing_sentinel_pairs": int(frame["year_exact"].eq(-1).sum()),
        "title_only": _metrics(queries, "title_only"),
        "weighted": _metrics(queries, "weighted"),
        "comparison": {
            "top1_changed_queries": sum(q["title_only"]["top1_ref_arxiv_id"]
                                        != q["weighted"]["top1_ref_arxiv_id"] for q in queries),
            "top5_order_changed_queries": sum(
                [r["ref_arxiv_id"] for r in q["title_only"]["top5"]]
                != [r["ref_arxiv_id"] for r in q["weighted"]["top5"]] for q in queries
            ),
            "improved_positive_queries": improved,
            "worsened_positive_queries": worsened,
            "unchanged_positive_rank_queries": len(positives) - improved - worsened,
        },
        "queries": queries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=DEFAULT_DATA_PATH, help="Parquet cần đánh giá")
    parser.add_argument("--output-json", type=Path, help="Ghi kết quả vào file JSON mới; không ghi đè")
    args = parser.parse_args(argv)
    try:
        if args.output_json and (args.output_json.suffix.lower() != ".json" or args.output_json.exists()):
            raise ValueError("Output phải là file .json mới, không được ghi đè file có sẵn")
        path = Path(args.path)
        result = evaluate_baselines(load_pairs(path))
        with path.open("rb") as handle:
            result["dataset"] = {"path": str(path.resolve()),
                                 "sha256": hashlib.file_digest(handle, "sha256").hexdigest()}
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            with args.output_json.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print("SO SÁNH HEURISTIC BASELINE M3 — TRỌNG SỐ CỐ ĐỊNH")
    print(f"Tổng candidate pairs: {result['total_pairs']}")
    print(f"Tổng queries: {result['total_queries']}")
    print(f"Queries có Positive: {result['positive_queries']}")
    print(f"Queries GT null: {result['null_gt_queries']}")
    print(f"GT có ID nhưng không có Positive trong pool: {result['known_gt_without_positive_queries']}")
    for key, name in [("title_only", "Baseline 1 — Title-only"), ("weighted", "Baseline 2 — Weighted")]:
        metrics = result[key]
        print(name)
        for metric in ["mrr_at_5", "mrr_at_5_positive_only", "hit_at_1_positive_only", "hit_at_5_positive_only"]:
            value = metrics[metric]
            print(f"  {metric}: {value:.6f}" if value is not None else f"  {metric}: N/A (không có Positive)")
    print("So sánh:", json.dumps(result["comparison"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
