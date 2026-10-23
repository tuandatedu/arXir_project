"""
Thống kê M2 cho Jupyter Book:
- parsing success rate, version coverage / publication
- element/entry counts trước vs sau dedup
- runtime: end-to-end wall, average / publication
- memory: peak RAM, output size
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parsing_stats(working_dir: Path) -> dict[str, Any]:
    """
    Cần code bên trong:
    - n_versions_total, n_versions_parsed, n_versions_empty (không TeX)
    - n_elements_before_dedup vs after
    - n_bib_before vs after
    - files ignored (off compilation path)
    """
    raise NotImplementedError("TODO(M2): parsing_stats")


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Ghi data/tables/metrics_m2.json."""
    raise NotImplementedError("TODO(M2): write_metrics")
