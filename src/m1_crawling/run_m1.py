"""Command-line entry point for the Milestone 1 crawler."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.common.config import ASSIGNED_IDS_FILE, WORKING_DIR
from .pipeline import run_milestone1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse paths and API credentials without printing the secret key."""
    # argparse generates the --help screen and validates command-line options.
    parser = argparse.ArgumentParser(description="Crawl assigned arXiv papers for M1")
    parser.add_argument("--ids", type=Path, default=ASSIGNED_IDS_FILE,
                        help="UTF-8 file containing one arXiv ID per line")
    parser.add_argument("--semantic-scholar-api-key", default=None,
                        help="Optional S2 API key; otherwise S2_API_KEY is used")
    parser.add_argument("--output", type=Path, default=WORKING_DIR,
                        help="Directory where per-paper corpus folders are written")
    # Read arguments from the command line, or from argv when called programmatically.
    args = parser.parse_args(argv)
    # An explicitly supplied key takes precedence over the environment variable.
    args.semantic_scholar_api_key = (args.semantic_scholar_api_key
                                     or os.environ.get("S2_API_KEY"))
    return args


def main(argv: list[str] | None = None) -> int:
    """Run M1 and return a process status code."""
    # Resolve options, fail early for a missing input file, then start the pipeline.
    args = parse_args(argv)
    if not args.ids.is_file():
        raise FileNotFoundError(f"Assigned ID file not found: {args.ids}")
    run_milestone1(args.ids, s2_api_key=args.semantic_scholar_api_key,
                   output_dir=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
