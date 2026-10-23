"""
CLI Milestone 1.

Ví dụ:
  python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
  S2_API_KEY=xxx python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Cần code bên trong:
    - --ids (bắt buộc): file UTF-8 một arXiv ID / dòng
    - --semantic-scholar-api-key (optional, fallback env S2_API_KEY)
    - --output (optional, mặc định data/working)
    """
    raise NotImplementedError("TODO(M1): parse_args")


def main(argv: list[str] | None = None) -> int:
    """Gọi run_milestone1, return 0 nếu xong (kể cả một số paper fail đã được log)."""
    raise NotImplementedError("TODO(M1): main")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
