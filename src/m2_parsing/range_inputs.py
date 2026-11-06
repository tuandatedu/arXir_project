"""Select M1 ranges, keep source checkpoints and Semantic Scholar tables separate."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from src.common.ids import normalize_arxiv_id
from src.common.io import write_json

from .batch_pipeline import discover_checkpoint_batches, run_checkpoint_batches

LOG = logging.getLogger(__name__)
RANGE_NUMBERS = (1, 2, 3, 4, 5)


def create_input_layout(input_root: Path) -> None:
    """Create empty input directories; never copy or modify the user's datasets."""
    for number in RANGE_NUMBERS:
        for kind in ("sources", "references"):
            (Path(input_root) / f"range_{number}" / kind).mkdir(parents=True, exist_ok=True)


def parse_range_selection(values: str | Sequence[str]) -> list[int]:
    """Accept '1', '1,3', '1 3', 'range_1 range_3', or 'all'."""
    text = values if isinstance(values, str) else " ".join(values)
    tokens = re.split(r"[\s,]+", text.strip().lower())
    if tokens == ["all"]:
        return list(RANGE_NUMBERS)
    selected = set()
    for token in tokens:
        token = token.removeprefix("range_")
        if token not in {str(number) for number in RANGE_NUMBERS}:
            raise ValueError("Chọn range 1 đến 5, ví dụ: 1,3 hoặc all.")
        selected.add(int(token))
    return sorted(selected)


def selection_output_dir(output_root: Path, selected: Sequence[int]) -> Path:
    return Path(output_root) / ("ranges_" + "_".join(map(str, selected)))


def _find_table(directory: Path, name: str) -> Path | None:
    candidates = [base / f"{name}.{suffix}" for base in (directory, directory / "tables")
                  for suffix in ("json", "jsonl") if (base / f"{name}.{suffix}").is_file()]
    if len(candidates) > 1:
        raise ValueError(f"Multiple {name} tables in {directory}; keep only one: {candidates}")
    return candidates[0] if candidates else None


def _iter_table(path: Path) -> Iterator[dict]:
    """Read M1 JSON arrays or stream JSONL. Load at most one range's JSON table."""
    with path.open(encoding="utf-8-sig") as stream:
        if path.suffix == ".json":
            rows = json.load(stream)
            if not isinstance(rows, list):
                raise ValueError(f"Expected a JSON array: {path}")
        else:
            rows = (json.loads(line) for line in stream if line.strip())
        for number, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"Expected an object: {path}, row {number}")
            yield row


def _prepare_reference_tables(input_root: Path, ids_by_range: dict[str, set[str]],
                              staging_dir: Path, require_references: bool) -> dict:
    """Validate M1 associations and stage combined tables before the M2 run starts."""
    report: dict = {"ranges": {}}
    with (staging_dir / "papers.jsonl").open("w", encoding="utf-8") as papers_out, \
            (staging_dir / "references.jsonl").open("w", encoding="utf-8") as refs_out:
        for label, source_ids in ids_by_range.items():
            directory = input_root / label / "references"
            paths = {name: _find_table(directory, name) for name in ("papers", "references")}
            if paths["references"] is None:
                message = f"{label}: chưa có references.json/jsonl trong {directory}"
                if require_references:
                    raise FileNotFoundError(message)
                LOG.warning("%s; M2 vẫn xử lý source LaTeX.", message)
            entry = {"n_source_papers": len(source_ids), "reference_status": (
                "missing" if paths["references"] is None else "provided"), "tables": {}}
            for name, output in (("papers", papers_out), ("references", refs_out)):
                path = paths[name]
                count = 0
                seen: set = set()
                citing_ids: set[str] = set()
                if path is not None:
                    for row in _iter_table(path):
                        try:
                            citing_id = normalize_arxiv_id(row.get("arxiv_id"))
                            if citing_id not in source_ids:
                                raise ValueError(f"arxiv_id {citing_id} không thuộc source của {label}")
                            row["arxiv_id"] = citing_id
                            key = citing_id
                            if name == "references":
                                row["ref_arxiv_id"] = normalize_arxiv_id(row.get("ref_arxiv_id"))
                                # Match the M1 table's identity: one S2 record per cited arXiv ID.
                                key = (citing_id, row["ref_arxiv_id"], row.get("ref_s2_id"))
                            if key in seen:
                                raise ValueError(f"Duplicate {name} row: {key}")
                            seen.add(key)
                        except (ValueError, TypeError) as exc:
                            raise ValueError(f"{path}, row {count + 1}: {exc}") from exc
                        citing_ids.add(citing_id)
                        output.write(json.dumps(row, ensure_ascii=False) + "\n")
                        count += 1
                entry["tables"][name] = {
                    "path": str(path.resolve()) if path else None,
                    "n_rows": count, "n_citing_papers": len(citing_ids),
                }
            report["ranges"][label] = entry
    return report


def run_selected_ranges(input_root: Path, selected: Sequence[int], working_dir: Path,
                        tables_dir: Path, workers: int = 1, resume: bool = False,
                        require_references: bool = False) -> dict:
    """Run chosen ranges with namespaced batch caches and a separate copy of M1 tables."""
    selected = parse_range_selection([str(number) for number in selected])
    input_root, working_dir, tables_dir = map(Path, (input_root, working_dir, tables_dir))
    if workers < 1:
        raise ValueError("workers must be >= 1")
    directories = {f"range_{number}": input_root / f"range_{number}" / "sources"
                   for number in selected}
    batches = discover_checkpoint_batches(directories)
    ids_by_range: dict[str, set[str]] = {label: set() for label in directories}
    for label, _, manifest in batches:
        ids_by_range[label].update(normalize_arxiv_id(value) for value in manifest["ids"])
    report_path = tables_dir / "input_report.json"
    if report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if previous.get("selected_ranges") != selected:
            raise ValueError(f"{tables_dir} chứa kết quả của range khác. Chọn --tables-dir khác.")
    # Stage and validate all references first. A bad input cannot truncate old final tables.
    with TemporaryDirectory(prefix="m2_references_") as temp:
        staging = Path(temp)
        report = _prepare_reference_tables(input_root, ids_by_range, staging, require_references)
        report.update({"selected_ranges": selected, "input_root": str(input_root.resolve()),
                       "source_directories": {label: str(path.resolve()) for label, path in directories.items()}})
        metrics = run_checkpoint_batches(directories, working_dir, tables_dir, workers, resume)
        m1_dir = tables_dir / "m1"
        m1_dir.mkdir(parents=True, exist_ok=True)
        for name in ("papers", "references"):
            shutil.copyfile(staging / f"{name}.jsonl", m1_dir / f"{name}.jsonl")
        metrics["selected_ranges"] = selected
        write_json(tables_dir / "metrics_m2.json", metrics)
        write_json(report_path, report)
    return metrics
