"""Bảng predictions (chỉ paper thuộc train/valid/test)."""

from __future__ import annotations

from src.common.schemas import PredictionRow


def write_predictions_table(rows: list[PredictionRow]) -> None:
    """Ghi data/tables/predictions.jsonl (working)."""
    raise NotImplementedError("TODO(M3): write_predictions_table")


def build_prediction_row(
    arxiv_id: str,
    partition: str,
    citation_key: str,
    groundtruth_arxiv_id: str | None,
    candidates: list[str | None],
) -> PredictionRow:
    """Pad/cắt candidates thành cand_1..cand_5."""
    raise NotImplementedError("TODO(M3): build_prediction_row")
