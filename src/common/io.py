"""Đọc/ghi JSONL, Parquet sharded, file ID. Không commit output vào git."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Iterable

from src.common.ids import normalize_arxiv_id


def load_assigned_ids(path: Path) -> list[str]:
    """
    Đọc file UTF-8: một arXiv ID / dòng.

    - Bỏ dòng trống và comment bắt đầu bằng '#'.
    - Gọi normalize_arxiv_id cho từng dòng.
    - Unique, giữ thứ tự.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Assigned IDs file not found: {path}")
    seen: set[str] = set()
    ids: list[str] = []
    for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            arxiv_id = normalize_arxiv_id(stripped)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            ids.append(arxiv_id)
    return ids


def write_json(path: Path, payload: Any) -> None:
    """Ghi JSON UTF-8, indent=2, tạo parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_json(path: Path) -> Any:
    """Đọc JSON."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Ghi JSON Lines (một object / dòng) — tiện working data M1/M2."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Đọc JSON Lines thành list[dict]."""
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_parquet_shard(path: Path, rows: list[dict[str, Any]]) -> None:
    """
    Ghi một file .parquet (pandas/pyarrow).

    - DataFrame từ rows, dtype khớp schemas.py (list[str] = pyarrow list).
    - Cột nullable đúng như đề (venue, year, groundtruth_arxiv_id, cand_*).
    """
    import pandas as pd

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    # Arrow không suy luận được list[str] từ list rỗng / Python object columns.
    for column in frame.columns:
        series = frame[column]
        if series.dtype == object:
            sample = next((value for value in series if value is not None), None)
            if isinstance(sample, list):
                frame[column] = series.apply(
                    lambda cell: list(cell) if cell is not None else None)
    frame.to_parquet(path, index=False)


def read_parquet_table(directory: Path) -> list[dict[str, Any]]:
    """Đọc mọi *.parquet trong directory (một Hugging Face config)."""
    import pandas as pd

    directory = Path(directory)
    files = sorted(directory.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in {directory}")
    frames = [pd.read_parquet(file) for file in files]
    merged = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    return merged.to_dict(orient="records")


def dataclass_to_dict(row: object) -> dict[str, Any]:
    """dataclasses.asdict — dùng trước khi write_jsonl / parquet."""
    if not dataclasses.is_dataclass(row) or isinstance(row, type):
        raise TypeError(f"Expected a dataclass instance, got {type(row).__name__}")
    return dataclasses.asdict(row)
