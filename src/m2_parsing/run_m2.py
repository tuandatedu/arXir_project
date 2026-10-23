"""
CLI Milestone 2.

  python -m src.m2_parsing.run_m2
"""

from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """--working-dir optional, mặc định data/working."""
    raise NotImplementedError("TODO(M2): parse_args")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("TODO(M2): main")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
