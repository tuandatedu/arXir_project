"""Run Milestone 1 end to end: crawl arXiv -> Semantic Scholar -> tables -> validation -> report.

Example (one student's range, first batch only; --batches 0 = every missing batch):

    python -m src.m1_crawling.run_m1_all --range 5 --data-dir data/m1_range5 --batches 1

Every step is resumable; re-running skips finished batches and finished references.
Exit status: 0 = done and tables valid, 1 = tables have validation errors, 3 = crawl aborted.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from src.common.io import write_json
from .batch_references import crawl_references
from .build_tables import build_tables
from .runtime_tracking import checkpoint_state, record_runtime, utc_now
from .validate_tables import validate_tables

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--range", type=int, default=0, choices=range(6), dest="range_number",
                   help="0=all 5 ranges, 1..5=one student's range")
    p.add_argument("--data-dir", type=Path, required=True,
                   help="Persistent folder (Drive on Colab): batch_*, reference_*, tables/")
    p.add_argument("--tables-dir", type=Path, default=None, help="default: <data-dir>/tables")
    p.add_argument("--batch-size", type=int, default=50, help="keep unchanged when resuming")
    p.add_argument("--batches", type=int, default=1, help="new batches to crawl; 0 = all missing")
    p.add_argument("--workers", type=int, default=1, help="assignment asks for one connection at a time")
    p.add_argument("--delay", type=float, default=3.1)
    p.add_argument("--retries", type=int, default=0, help="HTTP retries per arXiv request")
    p.add_argument("--retry-failed", action="store_true",
                   help="Recovery: retry only failed papers of existing batches")
    p.add_argument("--retry-empty", action="store_true",
                   help="also re-request papers whose S2 reference list was empty")
    p.add_argument("--verify-boundaries", action="store_true")
    p.add_argument("--s2-api-key", default=None, help="else env S2_API_KEY")
    p.add_argument("--skip-crawl", action="store_true")
    p.add_argument("--skip-references", action="store_true")
    p.add_argument("--no-report", action="store_true", help="skip export_reports")
    return p


def _crawl(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-u", "-m", "src.m1_crawling.run_arxiv_only",
           "--range", str(args.range_number), "--batch-size", str(args.batch_size),
           "--backup-dir", str(args.data_dir), "--delay", str(args.delay),
           "--workers", str(args.workers), "--next", str(args.batches),
           "--retries", str(args.retries)]
    if args.verify_boundaries:
        cmd.append("--verify-boundaries")
    if args.retry_failed:
        cmd.append("--retry-failed")
    before, started_at, start = checkpoint_state(args.data_dir), utc_now(), time.perf_counter()
    exit_code = -1
    try:
        exit_code = subprocess.run(cmd, cwd=REPO_ROOT).returncode
    finally:
        # Same ledger as the notebook, so export_reports sums wall-clock time correctly.
        try:
            record_runtime(args.data_dir, mode="recovery" if args.retry_failed else "fast",
                           range_id=args.range_number, batch_size=args.batch_size,
                           batches_requested=args.batches,
                           elapsed_seconds=time.perf_counter() - start, exit_code=exit_code,
                           started_at_utc=started_at, before=before,
                           after=checkpoint_state(args.data_dir))
        except OSError as exc:
            print(f"[WARNING] Không ghi được runtime_history.csv: {exc}")
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = args.tables_dir or args.data_dir / "tables"
    api_key = args.s2_api_key or os.environ.get("S2_API_KEY")
    steps: dict[str, float] = {}

    if not args.skip_crawl:
        print("\n=== 1/5 arXiv: metadata + source .tex/.bib ===", flush=True)
        t0 = time.perf_counter()
        code = _crawl(args)
        steps["crawl_arxiv_seconds"] = round(time.perf_counter() - t0, 3)
        if code not in (0, 2):  # 2 = some papers failed; checkpoints are still valid
            print(f"Crawler dừng với mã {code}.")
            return 3

    if not args.skip_references:
        print("\n=== 2/5 Semantic Scholar: reference ===", flush=True)
        t0 = time.perf_counter()
        crawl_references(args.data_dir, retry_empty=args.retry_empty, api_key=api_key)
        steps["crawl_references_seconds"] = round(time.perf_counter() - t0, 3)

    print("\n=== 3/5 Dựng bảng papers, references ===", flush=True)
    t0 = time.perf_counter()
    build = build_tables(args.data_dir, tables_dir)
    steps["build_tables_seconds"] = round(time.perf_counter() - t0, 3)
    print(f"papers: {build['papers_rows']} dòng | references (có arXiv ID): {build['references_rows']} dòng")
    missing = build["references"]["papers_without_reference_data"]
    if missing:
        print(f"{len(missing)} paper chưa có dữ liệu reference (lỗi hoặc chưa crawl): "
              f"{', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}")

    print("\n=== 4/5 Kiểm tra bảng ===", flush=True)
    validation = validate_tables(tables_dir)

    export_summary = None
    if not args.no_report:
        print("\n=== 5/5 Export report ===", flush=True)
        try:
            from .export_reports import export_reports
            export_summary = export_reports(args.data_dir)
            print(f"Report: {args.data_dir / 'reports'}")
        except Exception as exc:  # e.g. no checkpoint yet
            print(f"[WARNING] export_reports không chạy được: {exc}")

    write_json(tables_dir / "m1_run_summary.json", {
        "finished_at_utc": utc_now(), "range": args.range_number, "steps_seconds": steps,
        "build": build, "validation_ok": validation["ok"],
        "crawl_summary": export_summary})
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())