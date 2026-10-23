"""
CLI Milestone 3.

  python -m src.m3_matching.run_m3
  python -m src.m3_matching.run_m3 --export-only
"""

from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    --labels-dir mặc định data/labels
    --export-only: chỉ đóng gói Parquet từ tables đã có
    --seed split
    """
    raise NotImplementedError("TODO(M3): parse_args")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("TODO(M3): main")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
