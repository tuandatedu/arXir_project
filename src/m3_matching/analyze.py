"""Số liệu matching cho poster: size split, label source, MRR, phân bố candidate."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def matching_stats(labels: dict, predictions: list[dict]) -> dict[str, Any]:
    """n_manual, n_auto, |Q| từng split, tỷ lệ GT null, coverage cand_1."""
    raise NotImplementedError("TODO(M3): matching_stats")


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Ghi data/tables/metrics_m3.json."""
    raise NotImplementedError("TODO(M3): write_metrics")
