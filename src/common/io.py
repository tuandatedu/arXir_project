"""Small, explicit readers and writers used by all milestones."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from .ids import normalize_arxiv_id


def load_assigned_ids(path: Path) -> list[str]:
    """Load IDs, ignoring blank/comment lines and preserving first-seen order."""
    # Keep a list for input order and a set for quick duplicate detection.
    result: list[str] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            # Ignore whitespace-only lines and whole-line comments in the ID file.
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                # Store canonical base IDs so duplicates with vN still collapse together.
                arxiv_id = normalize_arxiv_id(line)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid arXiv ID at {path}:{line_no}: {line!r}") from exc
            if arxiv_id not in seen:
                seen.add(arxiv_id)
                result.append(arxiv_id)
    return result


def write_json(path: Path, payload: Any) -> None:
    """Write readable UTF-8 JSON and create its parent directory if needed."""
    path = Path(path)
    # Make nested output paths automatically before opening the file.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    """Read a UTF-8 JSON file."""
    # utf-8-sig also accepts files that begin with a Windows byte-order mark.
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write one JSON object per line; an empty input creates an empty file."""
    path = Path(path)
    # Ensure the output directory exists, even when no rows are produced.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            # One compact JSON object per line keeps the file streamable.
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON Lines and report the exact line containing malformed JSON."""
    result = []
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            # Blank lines are harmless; each non-blank line must be an object.
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Expected a JSON object at {path}:{line_no}")
                result.append(row)
    return result


def write_parquet_shard(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a Parquet file, using pyarrow when installed (including empty tables)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # from_pylist keeps list-valued columns as Arrow lists, not JSON strings.
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def read_parquet_table(directory: Path) -> list[dict[str, Any]]:
    """Read and concatenate every Parquet shard in a table directory."""
    import pyarrow.parquet as pq

    # Sort shard names so output order is stable across runs.
    paths = sorted(Path(directory).glob("*.parquet"))
    return [row for path in paths for row in pq.read_table(path).to_pylist()]


def dataclass_to_dict(row: object) -> dict[str, Any]:
    """Convert a dataclass instance to a plain dictionary."""
    # dataclasses.is_dataclass also returns True for the class itself; reject that case.
    if not is_dataclass(row) or isinstance(row, type):
        raise TypeError("row must be a dataclass instance")
    return asdict(row)
