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
from .batch_pipeline import run_checkpoint_batches
from .range_inputs import (create_input_layout, parse_range_selection,
                           run_selected_ranges, selection_output_dir)


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
    parser.add_argument("--tables-dir", type=Path,
                        help="Directory for final elements, hierarchy, bibtex and metrics")
    parser.add_argument("--batch-dir", type=Path, help="Restore M1 batch_*.tar.gz checkpoints before parsing")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel checkpoint batches (default: 1; batch-dir or range mode)")
    parser.add_argument("--resume", action="store_true",
                        help="Reuse completed checkpoint batches after an interrupted run")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ranges", nargs="+", help="Ranges to run: 1 3, 1,3 or all")
    selection.add_argument("--select-ranges", action="store_true",
                           help="Prompt for ranges to run")
    parser.add_argument("--input-root", type=Path, default=config.DATA_DIR / "input",
                        help="Contains range_1 through range_5, each with sources/ and references/")
    parser.add_argument("--output-root", type=Path, default=config.DATA_DIR / "output" / "m2",
                        help="Range outputs (default: data/output/m2/ranges_<selection>)")
    parser.add_argument("--init-layout", action="store_true", help="Create empty input folders and exit")
    parser.add_argument("--require-references", action="store_true",
                        help="Fail if a selected range has no M1 references table")
    args = parser.parse_args(argv)
    range_mode = args.ranges is not None or args.select_ranges
    if range_mode and (args.batch_dir is not None or args.raw_only or args.arxiv_ids):
        parser.error("--ranges/--select-ranges cannot combine with --batch-dir, --raw-only or --arxiv-id")
    if args.require_references and not range_mode:
        parser.error("--require-references requires --ranges or --select-ranges")
    if args.init_layout and range_mode:
        parser.error("Run --init-layout separately from --ranges/--select-ranges")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.init_layout:
        create_input_layout(args.input_root)
        print(f"Đã tạo 5 range, mỗi range có sources/ và references/: {args.input_root}")
        return 0
    if args.ranges is not None or args.select_ranges:
        create_input_layout(args.input_root)
        try:
            if args.select_ranges:
                print("Chọn range cần chạy: 1 đến 5; nhiều range: 1,3; toàn bộ: all.")
                while True:
                    try:
                        selected = parse_range_selection(input("Nhập range: "))
                        break
                    except ValueError as exc:
                        print(exc)
            else:
                selected = parse_range_selection(args.ranges)
            args.tables_dir = args.tables_dir or selection_output_dir(args.output_root, selected)
            print(f"Ranges: {', '.join(map(str, selected))}. Output: {args.tables_dir}")
            metrics = run_selected_ranges(args.input_root, selected, args.working_dir,
                                          args.tables_dir, args.workers, args.resume,
                                          args.require_references)
        except (ValueError, OSError, EOFError) as exc:
            print(f"Không chạy được M2: {exc}", file=sys.stderr)
            return 1
        print(f"M2: {metrics['n_publications']} publications, "
              f"{metrics['n_elements_after_dedup']} elements, "
              f"{metrics['n_bib_after']} BibTeX entries, "
              f"{metrics['n_versions_failed']} failed, {metrics['n_versions_partial']} partial versions. "
              f"Tables: {args.tables_dir}")
        return 2 if metrics["n_versions_failed"] or metrics["n_versions_partial"] else 0
    args.tables_dir = args.tables_dir or config.TABLES_DIR
    if args.batch_dir is not None and not args.raw_only:
        metrics = run_checkpoint_batches(args.batch_dir, args.working_dir, args.tables_dir,
                                         workers=args.workers, resume=args.resume)
        print(f"M2: {metrics['n_publications']} publications, "
              f"{metrics['n_elements_after_dedup']} elements, "
              f"{metrics['n_bib_after']} BibTeX entries, "
              f"{metrics['n_versions_failed']} failed, {metrics['n_versions_partial']} partial versions. "
              f"Tables: {args.tables_dir}")
        return 2 if metrics["n_versions_failed"] or metrics["n_versions_partial"] else 0
    if args.batch_dir is not None:
        parser_error = "--batch-dir requires the full M2 pipeline (omit --raw-only)"
        raise ValueError(parser_error)
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
        from src.common.io import read_json
        failed = read_json(args.tables_dir / "metrics_m2.json")["n_versions_failed"]
        partial = read_json(args.tables_dir / "metrics_m2.json")["n_versions_partial"]
        return 2 if failed or partial else (0 if ids else 1)
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
    # PowerShell's redirected streams may default to cp1252 even on Vietnamese Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
