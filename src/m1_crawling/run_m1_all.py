"""Orchestrate the batch M1 endgame: references -> tables -> validation -> summary.

This is the entry point the Colab notebook and the end-to-end CLI test use after
``run_arxiv_only`` finished the assigned range's batch checkpoints::

    python -m src.m1_crawling.run_m1_all --range 5 --data-dir data/m1_batch

Pipeline stages (each one resumable / skippable):

1. ``batch_references.crawl_references``  — Semantic Scholar references per paper,
   skipped with ``--skip-crawl`` when ``reference_*/`` is already complete.
2. ``build_tables.build_tables``          — papers.jsonl + references.jsonl from
   every valid ``batch_*`` pair and ``reference_*/`` folder.
3. ``validate_tables.validate_tables``    — schema/integrity check of both tables.
4. ``export_reports.export_reports``      — CSV/JSON reports, skipped with
   ``--no-report``.

Everything ends in ``tables/m1_run_summary.json`` with the build report and the
validation verdict; the process exit status is 0 only when validation passed.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from src.common.config import DATA_DIR
from src.common.io import write_json
from . import batch_references as br
from .assigned_ranges import RANGES
from .build_tables import build_tables
from .export_reports import export_reports
from .runtime_tracking import utc_now
from .validate_tables import validate_tables


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", type=int, default=0,
                        help="Assigned range number (1..5) recorded in the summary; "
                             "0 = all ranges / not specified")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help="Folder holding batch_*.tar.gz and reference_* checkpoints")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="Only rebuild and validate tables from existing checkpoints")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip exporting CSV/JSON report files")
    parser.add_argument("--retry-empty", action="store_true",
                        help="Re-fetch references for papers Semantic Scholar answered empty")
    parser.add_argument("--semantic-scholar-api-key", default=None,
                        help="Optional S2 API key; otherwise S2_API_KEY is used")
    parser.add_argument("--quiet", action="store_true",
                        help="Do not print crawl, validation, or report output")
    args = parser.parse_args(argv)
    args.semantic_scholar_api_key = (args.semantic_scholar_api_key
                                     or os.environ.get("S2_API_KEY"))
    return args


def _main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.range != 0 and args.range not in {item.number for item in RANGES}:
        print(f"Unknown range number: {args.range} "
              f"(valid: {sorted(item.number for item in RANGES)} or 0)", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir)
    processed: list[str] = []
    if not args.skip_crawl:
        # Reference crawling is resumable: only missing/error papers are requested.
        processed = br.crawl_references(data_dir, retry_empty=args.retry_empty,
                                        api_key=args.semantic_scholar_api_key)
    build = build_tables(data_dir)
    tables_dir = Path(build["tables_dir"])
    validation = validate_tables(tables_dir)
    if not args.no_report:
        # Reports need at least one batch checkpoint; tolerate an empty data dir.
        try:
            export_reports(data_dir)
        except FileNotFoundError as exc:
            print(f"[REPORT] skipped: {exc}", flush=True)
    summary = {
        "generated_at_utc": utc_now(),
        "data_dir": str(data_dir),
        "range": args.range or None,
        "reference_batches_processed": processed,
        "validation_ok": bool(validation["ok"]),
        "build": build,
        "validation": validation,
    }
    write_json(tables_dir / "m1_run_summary.json", summary)
    print(f"[TABLES] papers={build['papers_rows']} references={build['references_rows']} "
          f"validation={'OK' if summary['validation_ok'] else 'FAILED'} "
          f"-> {tables_dir / 'm1_run_summary.json'}", flush=True)
    return 0 if summary["validation_ok"] else 1


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.quiet:
        return _main(argv)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        previous_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            return _main(argv)
        finally:
            logging.disable(previous_disable)


if __name__ == "__main__":
    raise SystemExit(main())
