"""
CLI Milestone 2 — full pipeline, with optional raw hierarchy mode.

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

from .pipeline import run_milestone2, run_raw_hierarchy


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """--working-dir optional, mặc định data/working."""
    parser = argparse.ArgumentParser(
        description="Parse, standardize and deduplicate every M1 publication."
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
    parser.add_argument("--raw-only", action="store_true", help="Write only the parser's raw trees")
    parser.add_argument("--tables-dir", type=Path, default=config.TABLES_DIR,
                        help="Directory for final elements, hierarchy, bibtex and metrics")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.raw_only:
        summaries = run_raw_hierarchy(working_dir=args.working_dir, arxiv_ids=args.arxiv_ids)
    else:
        elements, hierarchy, bibtex = run_milestone2(
            working_dir=args.working_dir, arxiv_ids=args.arxiv_ids, tables_dir=args.tables_dir,
        )
        from .pipeline import _iter_publications
        ids = args.arxiv_ids if args.arxiv_ids is not None else _iter_publications(args.working_dir)
        print(f"M2: {len(ids)} publications, {len(elements)} elements, "
              f"{len(hierarchy)} hierarchy edges, {len(bibtex)} BibTeX entries. "
              f"Tables: {args.tables_dir}")
        return 0 if ids else 1
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
