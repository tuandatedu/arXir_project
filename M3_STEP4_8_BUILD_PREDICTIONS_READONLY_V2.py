#!/usr/bin/env python3
r"""Frozen M3 Range-1 predictions exporter V2, all 3 partitions, READ-ONLY INPUTS.

V2: specifically handles three audited Train queries with KNOWN GT but GT absent
from the frozen candidate pool. Their original non-null GT is preserved; their
Top-5 is still chosen only among existing candidate rows. No fake positives,
no relabeling, no GT-null conversion. Unexpected anomalies still fail loudly.

Uses the *already trained and locked* LR13. Streaming batch scoring keeps RAM
much smaller than reading 4,185,238 Train candidate pairs as a single DataFrame.
Keeps exactly the five best candidates for each BibTeX query over ALL batches,
with score descending and ORIGINAL PARQUET ROW ORDER as a stable tie-break.

NO training, model selection, thresholding, relabelling, dataset modification,
or network calls. Outputs must go to a brand-NEW directory outside frozen data.

Requires the trusted, user-created local .joblib artifact. NEVER deserialize
an untrusted joblib/pickle file.

PowerShell usage after extracting ZIP into project root:
  python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY_V2.py --selftest
  python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY_V2.py `
    --repo . `
    --lock .\outputs\step46_local_verify_20261125_01\verified_protocol_lock.json `
    --step47-dir .\outputs\step47_test_r1_20261125_01 `
    --diagnostic .\outputs\step48_train_gt_diagnosis_01\train_gt_diagnostic.json `
    --out-dir .\outputs\step48_predictions_r1_20261125_v2_01

The bundled test-only CSV is used to reproduce exactly the already reviewed
83 Test predictions. DO NOT use Test ranking/labels to change the frozen model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

GIT_COMMIT = "7f542abd88f4864b58bbca3fe183a0a4b7e7628b"
PROTOCOL_ID = "IntroDS_M3_R1_LR13_PreTest_2026-11-25_v1"
FEATURES = [
    "title_levenshtein", "title_token_sort", "title_token_set", "title_jaccard",
    "title_exact", "title_len_diff_ratio", "author_jaccard", "author_first_match",
    "author_any_match", "year_diff", "year_exact", "year_missing", "cite_count",
]
META = ["arxiv_id", "citation_key", "ref_arxiv_id", "groundtruth_arxiv_id", "label"]
COLUMNS = ["arxiv_id", "partition", "citation_key", "groundtruth_arxiv_id",
           "cand_1", "cand_2", "cand_3", "cand_4", "cand_5"]
PARTITIONS = ("train", "valid", "test")
EXPECTED = {
    "train": {
        "relative": "data/m3/range_1_frozen_20261123/prepared_dataset/train_pairs.parquet",
        "sha256": "f9cf5eb22ad1aad07b2db3135c26802cf00cd06fffc9e183dbaa3275c7dec27f",
        "rows": 4185238,
    },
    "valid": {
        "relative": "data/m3/range_1_frozen_20261123/prepared_dataset/valid_pairs.parquet",
        "sha256": "f62896841d6f3b5ebbc38ea098873eaa4daacaa34a22d5c4efc7c5cde49fd294",
        "rows": 4261,
        "queries": 53,
    },
    "test": {
        "relative": "data/m3/range_1_frozen_20261123/prepared_dataset/test_pairs.parquet",
        "sha256": "ed3beef0b3a40891a9bf0edbd3e922897ad4adac76efef182567801a1a3fc05d",
        "rows": 7747,
        "queries": 83,
        "size_bytes": 125000,
    },
}
EXPECTED_TEST_METRICS_SHA = EXPECTED["test"]["sha256"]
DEFAULT_REFERENCE_CSV = "M3_STEP4_8_FROZEN_TEST_83_ROWS.csv"

# These three exact cases were independently diagnosed on the frozen Train file
# (SHA256 pinned above) and cross-checked against manual labels. This allowlist
# is NOT a method of changing or generating labels.
EXPECTED_TRAIN_ABSENT = {
    ("2609.39989", "ref5", "2503.23037"),
    ("2609.39989", "ref7", "2605.25998"),
    ("2609.39989", "ref14", "2608.02880"),
}
EXPECTED_TRAIN_STATUS_COUNTS = {
    "KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL": 3,
    "OK_GT_NULL": 66810,
    "OK_ONE_POSITIVE": 75312,
}


def check_train_diagnostic(path: Path) -> tuple[set[tuple[str, str, str]], dict]:
    """Pin the signed-by-checksum Train anomaly diagnosis before any scoring.

    The diagnostic itself is verified against the known full frozen Train hash,
    exact query/status counts and hardcoded exception identities.
    """
    require(path.is_file(), f"Frozen Train diagnostic JSON missing: {path}")
    d = json_read(path)
    require(d.get("read_only") is True, "Diagnostic is not marked READ-ONLY")
    require(d.get("dataset_sha256") == EXPECTED["train"]["sha256"],
            "Diagnostic is not for the pinned frozen Train data")
    require(d.get("processed_candidate_pairs") == EXPECTED["train"]["rows"],
            "Diagnostic Train pair count differs")
    require(d.get("train_query_count") == 142125 and
            d.get("citing_publication_count") == 3664,
            "Diagnostic Train query/publication counts differ")
    require(d.get("status_counts") == EXPECTED_TRAIN_STATUS_COUNTS,
            "Diagnostic has an unexpected anomaly class or count")
    require(d.get("anomaly_query_count") == 3, "Diagnostic anomaly count differs")
    require(d.get("manual_label_matches_frozen_gt") is True,
            "Focus manual label was not cross-checked")
    anomalies = d.get("anomalies")
    require(isinstance(anomalies, list) and len(anomalies) == 3,
            "Diagnostic anomaly records must contain exactly three items")
    found = set()
    for a in anomalies:
        identity = (a.get("arxiv_id"), a.get("citation_key"),
                    a.get("groundtruth_arxiv_id"))
        require(identity not in found, f"Duplicate anomaly record: {identity}")
        found.add(identity)
        require(a.get("classification") == "KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL"
                and a.get("candidate_pairs") == 268
                and a.get("positive_pair_rows") == 0
                and a.get("target_id_occurrences") == 0
                and a.get("per_pair_label_mismatches") == 0
                and a.get("inconsistent_gt") is False,
                f"Unsupported anomaly in diagnostic: {identity}")
    require(found == EXPECTED_TRAIN_ABSENT,
            f"Unexpected missing-GT IDs: {sorted(found ^ EXPECTED_TRAIN_ABSENT)}")
    print("[PASS] Exactly 3 known Train GT-outside-pool exceptions verified")
    return found, d


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def blob_sha(path: Path) -> str:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def nullable_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    result = str(value)
    if not result:
        return None
    return result


def check_preflight(repo: Path, lockpath: Path, step47: Path, out: Path,
                    ref_csv: Path) -> tuple[Any, dict, dict]:
    """All frozen identities are checked before any scoring/writing."""
    require(repo.is_dir(), "Repository missing")
    require(lockpath.is_file(), "Step 4.6 verified lock missing")
    require(step47.is_dir(), "Step 4.7 output directory missing")
    require(not out.exists(), "Output already exists. Refusing to overwrite")
    require(ref_csv.is_file(), "Bundled frozen Test 83-row reference CSV missing")
    require(not out.is_relative_to(repo / "data"), "Output must be outside frozen data folder")
    require(not out.is_relative_to(step47), "Output must not overwrite Step 4.7")
    lock = json_read(lockpath)
    require(lock.get("protocol_id") == PROTOCOL_ID, "Protocol mismatch")
    require(lock.get("verification", {}).get("result") == "PASS", "Step 4.6 must PASS")
    require(lock.get("github", {}).get("commit_sha") == GIT_COMMIT, "Commit mismatch")
    require(lock.get("selected_model", {}).get("name") == "LR13", "Primary model was changed")
    require(lock.get("features") == FEATURES, "Frozen feature ordering changed")
    score = lock.get("scoring", {})
    require(score.get("positive_class") == 1 and score.get("top_k") == 5,
            "Frozen score class/Top5 changed")
    require(score.get("tie_break") == "candidate_original_row_order", "Frozen tie-break changed")
    require(score.get("abstention") == "none", "Unexpected abstention")
    require(lock.get("evaluation", {}).get("gt_null_rr") == 0, "Unexpected GT-null rule")
    require(lock.get("selected_model", {}).get("model_sha256") ==
            "a5052feb83eeac5f7be05fc1ca54f80feedc9907edd19186d0619762d4c02757",
            "Step4.7 frozen LR13 model hash differs")
    require(lock["training_r1"]["sha256"] == EXPECTED["train"]["sha256"], "Train lock hash differs")
    require(lock["validation_r1"]["sha256"] == EXPECTED["valid"]["sha256"], "Valid lock hash differs")
    for rel, git_sha in lock["github"]["source_git_blob_shas"].items():
        src = repo / rel
        require(src.is_file() and blob_sha(src) == git_sha, f"Frozen source changed: {rel}")
    metrics_path = step47 / "test_metrics.json"
    require(metrics_path.is_file(), "Step 4.7 test_metrics.json missing")
    test_metrics = json_read(metrics_path)
    require(test_metrics.get("protocol") == PROTOCOL_ID, "Step 4.7 protocol mismatch")
    require(test_metrics.get("official_primary") == "LR13", "Step 4.7 primary mismatch")
    provenance = test_metrics.get("provenance", {})
    require(provenance.get("test_sha256") == EXPECTED_TEST_METRICS_SHA,
            "Step 4.7 Test SHA mismatch")
    require(provenance.get("primary_model_sha256") == lock["selected_model"]["model_sha256"],
            "Step 4.7 primary model SHA mismatch")
    require(provenance.get("test_rows") == EXPECTED["test"]["rows"],
            "Step 4.7 Test row count mismatch")
    require(provenance.get("test_queries") == EXPECTED["test"]["queries"],
            "Step 4.7 Test query count mismatch")
    for part, spec in EXPECTED.items():
        path = (repo / spec["relative"]).resolve()
        require(path.is_file(), f"Frozen {part} Parquet missing: {path}")
        require(sha256(path) == spec["sha256"], f"Frozen {part} SHA-256 mismatch")
        if "size_bytes" in spec:
            require(path.stat().st_size == spec["size_bytes"], "Frozen Test size mismatch")
        print(f"[PASS] Frozen {part}: SHA-256 matches")
    model_path = (repo / lock["selected_model"]["artifact_relative_path"]).resolve()
    require(model_path.is_file(), "Trusted LR13 joblib missing")
    require(sha256(model_path) == lock["selected_model"]["model_sha256"],
            "Trusted LR13 model changed since 4.6/4.7")
    # ONLY deserialize your own trusted local trained model, never an unknown joblib file.
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    payload = joblib.load(model_path)
    require(isinstance(payload, dict) and payload.get("features") == FEATURES
            and "pipeline" in payload, "Invalid LR13 joblib structure")
    model = payload["pipeline"]
    require(isinstance(model, Pipeline) and len(model.steps) == 2 and
            isinstance(model.steps[0][1], StandardScaler) and
            isinstance(model.steps[1][1], LogisticRegression), "LR13 estimator changed")
    require(list(model.classes_) == [0, 1], "LR13 classes changed")
    require(int(model.named_steps["logisticregression"].n_features_in_) == 13,
            "LR13 13-feature fit mismatch")
    print("[PASS] Model/protocol/source hash checks; no training")
    return model, lock, test_metrics


def add_candidate(stats: dict, pub: str, key: str, ref: str, gt: str | None,
                  label: int, score: float, original_order: int,
                  ref_sign: int) -> None:
    """Streaming, exact stable score/rank top5 over all batches.

    A query may cross any number of Parquet batches/row groups. Within a query,
    earlier original rows WIN equal-score ties: heap tuple=(score, -row_index, ref).
    """
    q = (pub, key)
    rec = stats.get(q)
    if rec is None:
        rec = {"gt": gt, "count": 0, "positive": 0,
               "first": original_order, "heap": [], "sigxor": 0,
               "sigsum": 0}
        stats[q] = rec
    require(rec["gt"] == gt, f"GT inconsistency in {q}")
    require((label == 1) == (gt is not None and ref == gt),
            f"Pair label and GT disagree: {q} / {ref}")
    require(math.isfinite(float(score)) and 0.0 <= float(score) <= 1.0,
            f"Non-finite score or out-of-range for {q}")
    rec["count"] += 1
    rec["positive"] += label
    rec["sigxor"] ^= ref_sign
    rec["sigsum"] = (rec["sigsum"] + ref_sign) % (1 << 128)
    item = (float(score), -original_order, ref)
    h = rec["heap"]
    if len(h) < 5:
        heapq.heappush(h, item)
    elif item > h[0]:
        heapq.heapreplace(h, item)


def finalize_partition(stats: dict, partition: str,
                       allowed_absent: set[tuple[str, str, str]] | None = None
                      ) -> tuple[list[dict], dict]:
    """Validate labels and full publication-scoped candidate pools.

    GT known but out-of-pool is a valid *unmatchable* query under a frozen
    candidate pool, NEVER GT-null. For Train, accept only the three audited
    identities. For Valid/Test, preserve strict expected behavior.
    """
    require(stats, f"{partition} has no queries")
    permitted = set(allowed_absent or ())
    require(partition == "train" or not permitted,
            "GT-outside-pool exceptions are Train-only")
    rows = []
    pub_signature = {}
    positive = 0
    gt_null = 0
    observed_absent = set()
    pubs = set()
    for (pub, key), rec in stats.items():
        pubs.add(pub)
        n_pos = rec["positive"]
        gt = rec["gt"]
        if gt is None:
            require(n_pos == 0, f"GT-null has positive label: {(pub,key)}")
        elif n_pos == 1:
            pass  # already verified at pair level: label=1 iff candidate ref == GT
        elif n_pos == 0 and (pub, key, gt) in permitted:
            observed_absent.add((pub, key, gt))
        else:
            raise ValueError(f"Unexpected positive-count/GT mismatch: {(pub,key)} "
                             f"GT={gt!r}, positive_rows={n_pos}")
        positive += int(n_pos > 0)
        gt_null += int(gt is None)
        # A full m*n matrix has precisely the same n candidate IDs for EVERY
        # citation of a citing publication. We check count plus two 128-bit
        # deterministic fingerprints for low-memory validation of consistency.
        sig = (rec["count"], rec["sigxor"], rec["sigsum"])
        if pub in pub_signature:
            require(pub_signature[pub] == sig,
                    f"Candidate pool not equal between queries in publication {pub}")
        else:
            pub_signature[pub] = sig
        ranking = sorted(rec["heap"], reverse=True)
        ids = [v[2] for v in ranking]
        require(len(ids) == len(set(ids)), f"Duplicate Top5 candidate: {(pub,key)}")
        require(len(ids) == min(rec["count"], 5), f"Top5 length mismatch: {(pub,key)}")
        row = {"arxiv_id": pub, "partition": partition,
               "citation_key": key, "groundtruth_arxiv_id": rec["gt"]}
        row.update({f"cand_{i}": ids[i-1] if i <= len(ids) else None for i in range(1, 6)})
        rows.append(row)
    require(observed_absent == permitted,
            f"Expected Train GT-outside-pool exceptions not observed: "
            f"missing={sorted(permitted - observed_absent)}, "
            f"extra={sorted(observed_absent - permitted)}")
    require(positive + gt_null + len(observed_absent) == len(stats),
            f"{partition} query categories do not sum to total")
    summary = {"pairs": sum(r["count"] for r in stats.values()),
               "queries": len(stats), "positives": positive,
               "gt_null": gt_null, "known_gt_absent_from_candidate_pool": len(observed_absent),
               "known_gt_present": positive,
               "known_gt_total": positive + len(observed_absent),
               "known_gt_absent_queries": [
                    {"arxiv_id": pub, "citation_key": key, "groundtruth_arxiv_id": gt}
                    for pub, key, gt in sorted(observed_absent)
               ],
               "publications": len(pubs),
               "candidate_pool_sizes_by_publication":
                   {pub: sign[0] for pub, sign in sorted(pub_signature.items())}}
    return rows, summary


def stream_partition(model: Any, parquet_path: Path, partition: str,
                     batch_size: int,
                     allowed_absent: set[tuple[str, str, str]] | None = None
                    ) -> tuple[list[dict], dict]:
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(parquet_path)
    require(set(FEATURES + META).issubset(pf.schema_arrow.names),
            f"Missing features/meta in {partition}")
    require(pf.metadata.num_rows == EXPECTED[partition]["rows"],
            f"Unexpected row count in {partition}")
    stats = {}
    signature_cache = {}
    seen = 0
    for batch in pf.iter_batches(batch_size=batch_size, columns=FEATURES + META):
        df = batch.to_pandas()
        X = df[FEATURES].to_numpy(dtype=np.float64, copy=True)
        require(np.isfinite(X).all(), f"{partition} has NaN/Inf features")
        label = df["label"].to_numpy()
        require(np.isin(label, [0, 1]).all(), f"{partition} labels not 0/1")
        vals = model.predict_proba(X)[:, list(model.classes_).index(1)]
        require(len(vals) == len(df) and np.isfinite(vals).all(),
                f"{partition} model scores nonfinite/incomplete")
        # use itertuples for fewer allocations; combine metadata arrays
        for idx, (pub, key, ref, gt_raw, y) in enumerate(
            df[META].itertuples(index=False, name=None)
        ):
            require(pub is not None and key is not None and ref is not None and
                    not pd.isna(pub) and not pd.isna(key) and not pd.isna(ref),
                    f"{partition} has null candidate/query ID")
            pub, key, ref = str(pub), str(key), str(ref)
            gt = nullable_str(gt_raw)
            sig = signature_cache.get(ref)
            if sig is None:
                sig = int.from_bytes(hashlib.blake2b(
                    ref.encode("utf-8"), digest_size=16).digest(), "little")
                signature_cache[ref] = sig
            add_candidate(stats, pub, key, ref, gt, int(y),
                          float(vals[idx]), seen + idx, sig)
        seen += len(df)
        if seen % 500000 < batch_size or seen == pf.metadata.num_rows:
            print(f"[{partition}] scored {seen:,}/{pf.metadata.num_rows:,} pairs; "
                  f"queries={len(stats):,}", flush=True)
        del df, X, vals
    require(seen == EXPECTED[partition]["rows"], f"{partition} incomplete scan")
    rows, summary = finalize_partition(stats, partition, allowed_absent)
    require(summary["pairs"] == EXPECTED[partition]["rows"],
            f"{partition} pair total mismatch")
    if partition in ("valid", "test"):
        require(summary["queries"] == EXPECTED[partition]["queries"],
                f"{partition} query count mismatch")
    print(f"[PASS] {partition}: {summary['queries']:,} predictions, "
          f"{summary['publications']} publications, {summary['pairs']:,} pairs")
    return rows, summary


def read_csv_by_query(path: Path) -> dict[tuple[str, str], dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames == COLUMNS, f"Unexpected reference prediction schema in {path.name}")
        rows = {}
        for r in reader:
            key = (r["arxiv_id"], r["citation_key"])
            require(key not in rows, "Duplicate query in test reference")
            rows[key] = r
    return rows


def verify_exact_test(rows: list[dict], csvpath: Path,
                      test_metrics: dict) -> dict:
    known = read_csv_by_query(csvpath)
    require(len(known) == EXPECTED["test"]["queries"],
            "Frozen Test reference must have exactly 83 entries")
    observed = {(r["arxiv_id"], r["citation_key"]): r for r in rows}
    require(set(known) == set(observed), "Test query keys differ from Step 4.7")
    for key, prior in known.items():
        current = observed[key]
        for col in COLUMNS:
            expected_val = prior[col] or None
            require(current[col] == expected_val,
                    f"Test result changed from Step 4.7 for {key} / {col}: "
                    f"{current[col]!r} != {expected_val!r}")
    mrr_by_pub = defaultdict(list)
    for r in rows:
        gt = r["groundtruth_arxiv_id"]
        rr = (1 / (1 + [r[f"cand_{i}"] for i in range(1, 6)].index(gt))
              if gt is not None and gt in [r[f"cand_{i}"] for i in range(1, 6)]
              else 0.0)
        mrr_by_pub[r["arxiv_id"]].append(rr)
    for pr in test_metrics["per_publication"]:
        if pr["method"] != "LR13":
            continue
        scores = mrr_by_pub[pr["arxiv_id"]]
        require(len(scores) == pr["queries"] and math.isclose(
                    math.fsum(scores) / len(scores), pr["mrr_at_5_all_queries"],
                    rel_tol=0, abs_tol=1e-12),
                "Frozen Test MRR mismatch with Step4.7")
    print("[PASS] Test all 83 rows / all 415 candidate positions match Step 4.7 EXACTLY")
    return {"matched_queries": len(known), "matched_candidate_slots": len(known) * 5,
            "mrr_by_publication": {k: math.fsum(v)/len(v) for k, v in mrr_by_pub.items()}}


def check_valid_published_top5(rows: list[dict], expected_path: Path) -> dict:
    require(expected_path.is_file(), f"Missing locked Validation output: {expected_path}")
    with expected_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        mapping = {}
        for r in reader:
            key = (r["arxiv_id"], r["citation_key"], int(r["rank"]))
            require(key not in mapping, f"Duplicate validation rank {key}")
            mapping[key] = r["ref_arxiv_id"]
    observed = {}
    for row in rows:
        for i in range(1, 6):
            v = row[f"cand_{i}"]
            if v is not None:
                observed[(row["arxiv_id"], row["citation_key"], i)] = v
    require(mapping == observed, "Validation Top-5 changed relative to frozen LR13 output")
    print(f"[PASS] Validation all {len(mapping)} Top-5 ranks match Step 4.6 output")
    return {"matched_validation_top5_rows": len(mapping)}


def write_predictions_parquet(rows: list[dict], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([
        pa.field("arxiv_id", pa.string(), nullable=False),
        pa.field("partition", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("citation_key", pa.string(), nullable=False),
        pa.field("groundtruth_arxiv_id", pa.string(), nullable=True),
        *(pa.field(f"cand_{i}", pa.string(), nullable=True) for i in range(1,6)),
    ])
    require(bool(rows), "Empty final predictions")
    arrays = [pa.array([r[col] for r in rows], type=schema.field(col).type)
              for col in COLUMNS]
    table = pa.Table.from_arrays(arrays, schema=schema)
    pq.write_table(table, path, compression="zstd", row_group_size=65536)
    read = pq.ParquetFile(path)
    require(read.metadata.num_rows == len(rows), "Written Parquet row count mismatch")
    require(read.schema_arrow.equals(schema, check_metadata=False),
            "Written Parquet schema mismatch (dictionary/string/nullability)")
    part_counts = (read.read(columns=["partition"])
                   .column("partition").to_pylist())
    require({p: part_counts.count(p) for p in PARTITIONS} ==
            {p: sum(r["partition"] == p for r in rows) for p in PARTITIONS},
            "Parquet partition values mismatch")


def run(repo: Path, lockpath: Path, step47: Path, out: Path, reference: Path,
        batch_size: int, diagnostic_path: Path) -> None:
    require(batch_size > 0 and batch_size <= 250000, "Use 1 <= batch_size <= 250000")
    permitted_absent, diagnostic = check_train_diagnostic(diagnostic_path)
    model, lock, test_metrics = check_preflight(repo, lockpath, step47, out, reference)
    all_rows = []
    partition_summaries = {}
    publication_partition = {}
    for p in PARTITIONS:
        data, summary = stream_partition(
            model, repo / EXPECTED[p]["relative"], p, batch_size,
            allowed_absent=permitted_absent if p == "train" else None
        )
        for row in data:
            old = publication_partition.setdefault(row["arxiv_id"], p)
            require(old == p, f"Publication leakage across splits: {row['arxiv_id']}")
        partition_summaries[p] = summary
        if p == "valid":
            check_valid_published_top5(data,
                 repo / "outputs/lr13_full_20261125_01/validation_top5.csv")
        if p == "test":
            test_verified = verify_exact_test(data, reference, test_metrics)
        all_rows.extend(data)
    require(len(all_rows) == len({(r["arxiv_id"],r["citation_key"])
                                for r in all_rows}), "Duplicate query across partitions")
    require(set(r["partition"] for r in all_rows) == set(PARTITIONS), "Missing partition")
    report = {
        "status": "PASS", "scope": "Range 1 only (not all five team ranges)",
        "protocol": PROTOCOL_ID, "primary": "LR13", "github_commit": GIT_COMMIT,
        "model_sha256": lock["selected_model"]["model_sha256"],
        "input_frozen_sha256": {p: EXPECTED[p]["sha256"] for p in PARTITIONS},
        "partition_summary": partition_summaries,
        "distinct_source_publications": len(publication_partition),
        "total_prediction_rows": len(all_rows),
        "test_reproduced": test_verified,
        "test_never_used_to_select_model_or_hyperparameters": True,
        "training_gt_outside_candidate_pool_audit": {
            "count": 3,
            "queries": partition_summaries["train"]["known_gt_absent_queries"],
            "train_diagnostic_sha256": sha256(diagnostic_path),
            "handling": (
                "Preserve non-null groundtruth_arxiv_id; rank only the frozen candidate "
                "pool; do not fabricate the missing GT as a candidate or relabel the query"
            ),
            "other_partitions_known_gt_absent": {
                p: partition_summaries[p]["known_gt_absent_from_candidate_pool"]
                for p in ("valid", "test")
            },
        },
        "disclaimer": "Includes known automatic-label dependence; GT-null is not verified no-match",
    }
    out.mkdir(parents=True, exist_ok=False)
    parquet_path = out / "predictions.parquet"
    write_predictions_parquet(all_rows, parquet_path)
    report["predictions_parquet_sha256"] = sha256(parquet_path)
    with (out / "train_gt_outside_candidate_pool.csv").open(
            "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "arxiv_id", "citation_key", "groundtruth_arxiv_id",
            "candidate_pairs", "positive_pair_rows", "classification"
        ])
        writer.writeheader()
        for a in sorted(diagnostic["anomalies"], key=lambda a: (a["arxiv_id"], a["citation_key"])):
            writer.writerow({k: a[k] for k in writer.fieldnames})
    (out / "predictions_manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("\n=== SUCCESS: STEP 4.8 RANGE-1 PREDICTIONS PARQUET COMPLETED ===")
    for p in PARTITIONS:
        s = partition_summaries[p]
        print(f"[DONE] {p}: {s['queries']:,} queries; "
              f"{s['pairs']:,} candidate pairs; {s['publications']} publications")
    print(f"[SAVED] {parquet_path}")
    print(f"[SAVED] {out / 'predictions_manifest.json'}")
    print("[PASS] 3/142125 Train queries have known GT outside candidate pool: "
          "preserved as non-null GT, never fabricated as Top-5 candidate")
    print(f"[SAVED] {out / 'train_gt_outside_candidate_pool.csv'}")
    print("[SAFE] No refit, no tuning, no label change, no integration or Hugging Face upload")


def selftest() -> None:
    # Synthetic cases: ties, <5 / >5 candidates, query crossing batches,
    # GT-null and expected score ordering.  Does not load real data/models.
    stats = {}
    def sig(v):
        return int.from_bytes(hashlib.blake2b(v.encode(), digest_size=16).digest(), 'little')
    for idx, (ref, score) in enumerate([
        ("z", 0.5), ("a", 0.5), ("b", 0.8), ("c", 0.6),
        ("d", 0.9), ("e", 0.9), ("f", 0.7),
    ]):
        add_candidate(stats, "pub1", "key1", ref, "d", int(ref=="d"), score, idx, sig(ref))
    # Same 7 candidate IDs but another BibTeX query; here GT-null.
    for idx, ref in enumerate(["z","a","b","c","d","e","f"], start=7):
        add_candidate(stats, "pub1", "key2", ref, None, 0, 0.4, idx, sig(ref))
    # A smaller candidate pool for another publication.
    for idx, ref in enumerate(["x","y","z"], start=14):
        add_candidate(stats, "pub2", "key3", ref, "y", int(ref=="y"), 0.5, idx, sig(ref))
    # Same publication pool, but known GT is external to all frozen candidates.
    for idx, ref in enumerate(["z","a","b","c","d","e","f"], start=17):
        add_candidate(stats, "pub1", "missing", ref, "external", 0, 0.45, idx, sig(ref))
    try:
        finalize_partition(stats, "train")
        raise AssertionError("Should fail if the missing GT was not explicitly audited")
    except ValueError as e:
        assert "Unexpected positive-count/GT mismatch" in str(e)
    rows, summary = finalize_partition(stats, "train", {("pub1", "missing", "external")})
    assert summary == {
        "pairs":24, "queries":4, "positives":2, "gt_null":1,
        "known_gt_absent_from_candidate_pool":1,
        "known_gt_present":2, "known_gt_total":3,
        "known_gt_absent_queries":[{"arxiv_id":"pub1", "citation_key":"missing",
                                    "groundtruth_arxiv_id":"external"}],
        "publications":2,
        "candidate_pool_sizes_by_publication":{"pub1":7,"pub2":3}}
    assert [rows[0][f"cand_{i}"] for i in range(1, 6)] == ["d","e","b","f","c"]
    assert [rows[1][f"cand_{i}"] for i in range(1, 6)] == ["z","a","b","c","d"]
    assert rows[2]["cand_4"] is None and rows[2]["cand_5"] is None
    assert rows[3]["groundtruth_arxiv_id"] == "external"
    assert "external" not in [rows[3][f"cand_{i}"] for i in range(1,6)]
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p = Path(d) / "predictions.parquet"
            write_predictions_parquet(rows,p)
            assert pq.ParquetFile(p).metadata.num_rows == 3
        print("[PASS] Synthetic Parquet dictionary/nullable schema and read-back")
    except ModuleNotFoundError:
        print("[NOTE] pyarrow not installed in current environment; synthetic Parquet roundtrip skipped")
    print("[PASS] Synthetic streaming Top-5 heap: stable ties, 7/3 candidates, GT-null, full pool")
    print("[PASS] Synthetic known-GT-outside-pool: rejects unapproved, permits exact audited only")
    print("Selftest completed; no real data/model/Test touched")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--step47-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--diagnostic", type=Path,
                        help="Read-only Train diagnostic JSON from previous step (3 audited queries)")
    parser.add_argument("--reference-test-csv", type=Path,
                        default=Path(__file__).resolve().parent / DEFAULT_REFERENCE_CSV)
    parser.add_argument("--batch-size", type=int, default=50000)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
            return 0
        if any(x is None for x in [args.lock, args.step47_dir, args.out_dir]):
            parser.error("--lock, --step47-dir, --out-dir required")
        diag = (args.diagnostic if args.diagnostic is not None else
                args.repo / "outputs/step48_train_gt_diagnosis_01/train_gt_diagnostic.json")
        run(args.repo.resolve(), args.lock.resolve(), args.step47_dir.resolve(),
            args.out_dir.resolve(), args.reference_test_csv.resolve(), args.batch_size,
            diag.resolve())
        return 0
    except (ValueError, OSError, KeyError, TypeError, AssertionError, ImportError) as exc:
        print(f"\n[FAILED] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Nothing in Train/Validation/Test or models was modified.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
