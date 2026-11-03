"""
CLI Milestone 2 — cây phân cấp trước chuẩn hóa.

  python -m src.m2_parsing.run_m2
  python -m src.m2_parsing.run_m2 --working-dir data/working
  python -m src.m2_parsing.run_m2 --arxiv-id 2310.12345
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.common import config

from .pipeline import run_raw_hierarchy


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """--working-dir optional, mặc định data/working."""
    parser = argparse.ArgumentParser(
        description="Parse M1 TeX sources into per-version trees (before cleanup/dedup)."
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        default=config.WORKING_DIR,
        help="M1 working corpus (default: data/working)",
    )
    parser.add_argument(
        "--arxiv-id",
        action="append",
        dest="arxiv_ids",
        default=None,
        help="Parse only this arXiv id (repeatable). Default: every publication in working-dir.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    summaries = run_raw_hierarchy(
        working_dir=args.working_dir,
        arxiv_ids=args.arxiv_ids,
    )
    n_pub = len(summaries)
    n_ver = sum(item["n_versions"] for item in summaries)
    n_ok = sum(item["n_parsed"] for item in summaries)
    n_empty = sum(item["n_empty"] for item in summaries)
    print(
        f"Parsed {n_pub} publications, {n_ver} versions "
        f"({n_ok} with TeX, {n_empty} empty). "
        f"Trees: {{working}}/{{id}}/parsed/raw/vN/"
    )
    if n_pub == 0:
        print(
            "No publications found. Run Milestone 1 first or pass --working-dir.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
