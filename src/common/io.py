"""Đọc/ghi JSONL, Parquet sharded, file ID. Không commit output vào git."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def load_assigned_ids(path: Path) -> list[str]:
    """
    Đọc file UTF-8: một arXiv ID / dòng.

    Cần code bên trong:
    - Bỏ dòng trống và comment bắt đầu bằng '#'.
    - Gọi normalize_arxiv_id cho từng dòng.
    - Unique, giữ thứ tự.
    """
    raise NotImplementedError("TODO(common): load_assigned_ids")


def write_json(path: Path, payload: Any) -> None:
    """Ghi JSON UTF-8, indent=2, tạo parent dirs."""
    raise NotImplementedError("TODO(common): write_json")


def read_json(path: Path) -> Any:
    """Đọc JSON."""
    raise NotImplementedError("TODO(common): read_json")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ghi JSON Lines (một object / dòng) — tiện working data M1/M2."""
    raise NotImplementedError("TODO(common): write_jsonl")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Đọc JSON Lines thành list[dict]."""
    raise NotImplementedError("TODO(common): read_jsonl")


def write_parquet_shard(path: Path, rows: list[dict[str, Any]]) -> None:
    """
    Ghi một file .parquet (pandas/pyarrow).

    Cần code bên trong:
    - DataFrame từ rows, dtype khớp schemas.py (list[str] = pyarrow list).
    - Cột nullable đúng như đề (venue, year, groundtruth_arxiv_id, cand_*).
    """
    raise NotImplementedError("TODO(common): write_parquet_shard")


def read_parquet_table(directory: Path) -> list[dict[str, Any]]:
    """Đọc mọi *.parquet trong directory (một Hugging Face config)."""
    raise NotImplementedError("TODO(common): read_parquet_table")


def dataclass_to_dict(row: object) -> dict[str, Any]:
    """dataclasses.asdict — dùng trước khi write_jsonl / parquet."""
    raise NotImplementedError("TODO(common): dataclass_to_dict")
