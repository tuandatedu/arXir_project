#!/usr/bin/env python3
r"""Read-only diagnostic for M3 Step 4.8 Train Positive-count/GT mismatch.

This tool does NOT train, change data, evaluate Test, or modify the frozen model.
It reads only the required metadata columns of frozen Range-1 train_pairs.parquet,
checks per-query groundtruth consistency and positive candidate multiplicity,
and writes a NEW diagnostic report outside data/.

Usage (PowerShell, project root):
  python .\M3_STEP4_8_DIAGNOSE_TRAIN_READONLY.py --selftest
  python .\M3_STEP4_8_DIAGNOSE_TRAIN_READONLY.py `
    --repo . `
    --out-dir .\outputs\step48_train_gt_diagnosis_01

Optional: --batch-size 100000; --expected-gt 2503.23037.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRAIN_REL = Path("data/m3/range_1_frozen_20261123/prepared_dataset/train_pairs.parquet")
TRAIN_SHA256 = "f9cf5eb22ad1aad07b2db3135c26802cf00cd06fffc9e183dbaa3275c7dec27f"
TRAIN_N = 4185238
META = ["arxiv_id", "citation_key", "ref_arxiv_id", "groundtruth_arxiv_id", "label"]
FOCUS = ("2609.39989", "ref5")
DEFAULT_GT = "2503.23037"


def normalized_gt(value: Any) -> str | None:
    if value is None:
        return None
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except ImportError:
        pass
    t = str(value).strip()
    return t if t else None


@dataclass
class Group:
    gt: str | None
    count: int = 0
    n_positive: int = 0
    gt_id_hits: int = 0
    positive_ids: set[str] = field(default_factory=set)
    first_candidates: list[str] = field(default_factory=list)
    inconsistent_gt: bool = False
    pair_label_mismatch: int = 0


def add(rows: dict[tuple[str,str], Group], pub: str, key: str, ref: str,
        gt: str | None, label: int) -> None:
    q = (pub,key)
    if q not in rows:
        rows[q] = Group(gt=gt)
    r = rows[q]
    r.count += 1
    if len(r.first_candidates) < 8:
        r.first_candidates.append(ref)
    if r.gt != gt:
        r.inconsistent_gt = True
    if label not in (0,1):
        r.pair_label_mismatch += 1
        return
    r.n_positive += label
    if label:
        r.positive_ids.add(ref)
    if gt is not None and ref == gt:
        r.gt_id_hits += 1
    if (label == 1) != (gt is not None and ref == gt):
        r.pair_label_mismatch += 1


def analyze(rows: dict[tuple[str,str], Group], focus=FOCUS) -> dict:
    classifications = Counter()
    anomalies=[]
    pubs=Counter()
    for (pub,key), r in rows.items():
        pubs[pub] += 1
        if r.inconsistent_gt:
            status="INCONSISTENT_GT_WITHIN_QUERY"
        elif r.pair_label_mismatch:
            status="PAIR_LABEL_GT_INCONSISTENT"
        elif r.gt is None and r.n_positive==0:
            status="OK_GT_NULL"
        elif r.gt is None and r.n_positive:
            status="INVALID_POSITIVE_WITH_GT_NULL"
        elif r.gt is not None and r.n_positive==1 and r.gt_id_hits==1:
            status="OK_ONE_POSITIVE"
        elif r.gt is not None and r.n_positive==0 and r.gt_id_hits==0:
            status="KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL"
        elif r.gt is not None and r.n_positive>1 and r.gt_id_hits>1:
            status="DUPLICATED_POSITIVE_CANDIDATE_ID"
        else:
            status="OTHER_GT_POSITIVE_CONTRADICTION"
        classifications[status] += 1
        if not status.startswith("OK_"):
            anomalies.append({"arxiv_id":pub,"citation_key":key,"classification":status,
                "groundtruth_arxiv_id":r.gt,"candidate_pairs":r.count,
                "positive_pair_rows":r.n_positive,"target_id_occurrences":r.gt_id_hits,
                "positive_candidate_ids":sorted(r.positive_ids),
                "per_pair_label_mismatches":r.pair_label_mismatch,
                "inconsistent_gt":r.inconsistent_gt})
    f=rows.get(focus)
    focused={"arxiv_id":focus[0],"citation_key":focus[1],"found":f is not None}
    if f:
        focused.update({"groundtruth_arxiv_id":f.gt,"candidate_pairs":f.count,
            "positive_pair_rows":f.n_positive,"target_id_occurrences":f.gt_id_hits,
            "positive_candidate_ids":sorted(f.positive_ids),"candidate_ids_first_8":f.first_candidates,
            "inconsistent_gt":f.inconsistent_gt,"per_pair_label_mismatches":f.pair_label_mismatch})
        matches=[a for a in anomalies if (a["arxiv_id"],a["citation_key"])==focus]
        focused["classification"]=(matches[0]["classification"] if matches else "PASS")
    return {"train_query_count":len(rows),"citing_publication_count":len(pubs),
            "status_counts":dict(sorted(classifications.items())),
            "anomaly_query_count":len(anomalies),"anomalies":anomalies,
            "focus_query":focused}


def checksum(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def run(repo: Path, out: Path, batch_size: int, expected_gt: str) -> None:
    if not repo.is_dir():
        raise ValueError("Repository not found")
    train=(repo/TRAIN_REL).resolve()
    if not train.is_file():
        raise ValueError(f"Frozen Train missing: {train}")
    if out.exists():
        raise ValueError("Output directory already exists; choose a NEW directory")
    if out.is_relative_to((repo/"data").resolve()):
        raise ValueError("Output cannot be inside frozen data/")
    if not 1 <= batch_size <= 250000:
        raise ValueError("batch-size must be 1..250000")
    actual=checksum(train)
    if actual!=TRAIN_SHA256:
        raise ValueError(f"Frozen Train SHA-256 CHANGED: {actual}")
    print("[PASS] Frozen Train SHA256 verified",flush=True)
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(train)
    if pf.metadata.num_rows!=TRAIN_N:
        raise ValueError(f"Unexpected Train rows: {pf.metadata.num_rows}")
    if not set(META).issubset(pf.schema_arrow.names):
        raise ValueError(f"Missing metadata columns: {sorted(set(META)-set(pf.schema_arrow.names))}")
    rows: dict[tuple[str,str], Group]={}
    processed=0
    for batch in pf.iter_batches(columns=META,batch_size=batch_size):
        frame=batch.to_pandas()
        for pub,key,ref,raw_gt,y in frame.itertuples(index=False,name=None):
            if pub is None or key is None or ref is None:
                raise ValueError("Null query/candidate ID")
            add(rows,str(pub),str(key),str(ref),normalized_gt(raw_gt),int(y))
        processed+=len(frame)
        if processed%500000 < batch_size or processed==TRAIN_N:
            print(f"[SCAN] {processed:,}/{TRAIN_N:,} metadata rows; {len(rows):,} queries",flush=True)
    if processed!=TRAIN_N:
        raise ValueError(f"Incomplete scan: {processed}")
    result=analyze(rows)
    result.update({"read_only":True,"dataset":str(TRAIN_REL),"dataset_sha256":actual,
                   "processed_candidate_pairs":processed,"manual_label_crosscheck_for_focus":expected_gt,
                   "manual_label_matches_frozen_gt":result["focus_query"].get("groundtruth_arxiv_id")==expected_gt})
    if not result["manual_label_matches_frozen_gt"]:
        print("[WARNING] Focus GT differs from manual label (or query missing)")
    out.mkdir(parents=True,exist_ok=False)
    (out/"train_gt_diagnostic.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("\n=== TRAIN GT DIAGNOSTIC (READ-ONLY) ===")
    print("FOCUS:",json.dumps(result["focus_query"],ensure_ascii=False))
    print("STATUS COUNTS:",json.dumps(result["status_counts"],ensure_ascii=False))
    print("ANOMALIES:",result["anomaly_query_count"])
    print("[SAVED]",out/"train_gt_diagnostic.json")
    print("No models, Train, Validation or Test were changed")


def selftest() -> None:
    rows={}
    for ref in ["a","b","c"]:
        add(rows,"p","missing",ref,"external",0)
    for ref in ["a","b","b","c"]:
        add(rows,"p","duplicate",ref,"b",int(ref=="b"))
    for ref in ["a","b","c"]:
        add(rows,"p","fine",ref,"b",int(ref=="b"))
    for ref in ["a","b","c"]:
        add(rows,"p","none",ref,None,0)
    a=analyze(rows,focus=("p","missing"))
    assert a["status_counts"]=={
        "DUPLICATED_POSITIVE_CANDIDATE_ID":1,
        "KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL":1,
        "OK_GT_NULL":1,"OK_ONE_POSITIVE":1},a["status_counts"]
    assert a["focus_query"]["classification"]=="KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL"
    print("[PASS] Synthetic classification: missing-GT / duplicated-positive / valid-positive / GT-null")
    print("Selftest done; no data/model/Test accessed")


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--repo",type=Path,default=Path("."))
    p.add_argument("--out-dir",type=Path)
    p.add_argument("--batch-size",type=int,default=100000)
    p.add_argument("--expected-gt",default=DEFAULT_GT)
    args=p.parse_args()
    try:
        if args.selftest:
            selftest()
            return 0
        if args.out_dir is None:
            p.error("--out-dir is required without --selftest")
        run(args.repo.resolve(),args.out_dir.resolve(),args.batch_size,args.expected_gt)
        return 0
    except (ValueError,TypeError,RuntimeError,OSError,ImportError) as exc:
        print(f"[FAILED] {type(exc).__name__}: {exc}",file=sys.stderr)
        print("Frozen input and models unchanged",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
