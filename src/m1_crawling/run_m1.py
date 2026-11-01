"""
CLI Milestone 1.

Ví dụ:
  python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
  S2_API_KEY=xxx python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from src.common import config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    - --ids (bắt buộc): file UTF-8 một arXiv ID / dòng
    - --semantic-scholar-api-key (optional, fallback env S2_API_KEY)
    - --output (optional, mặc định data/working)
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.m1_crawling.run_m1",
        description="Milestone 1: crawl assigned arXiv IDs end-to-end.")
    parser.add_argument(
        "--ids", type=Path, required=True,
        help="UTF-8 file with one arXiv ID per line")
    parser.add_argument(
        "--semantic-scholar-api-key", default=None,
        help="Semantic Scholar API key (fallback: env S2_API_KEY)")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Working corpus directory (default: data/working)")
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Gọi run_milestone1, return 0 nếu xong (kể cả một số paper fail đã được log)."""
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.output is not None:
        config.WORKING_DIR = Path(args.output)

    api_key = args.semantic_scholar_api_key or os.environ.get("S2_API_KEY")

    from .pipeline import run_milestone1
    papers, references = run_milestone1(args.ids, s2_api_key=api_key)
    logging.getLogger(__name__).info(
        "Wrote %d papers / %d references (arXiv-carrying) to %s",
        len(papers), len(references), config.TABLES_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
