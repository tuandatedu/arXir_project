"""Orchestrator M3: clean → label quota → split → train → predict top-5 → MRR@5 → HF."""

from __future__ import annotations

from src.common.schemas import PredictionRow


def run_labelling() -> dict:
    """Load manual jsonl + auto_label pool; validate_label_quota."""
    raise NotImplementedError("TODO(M3): run_labelling")


def run_modeling(labels: dict) -> tuple[object, dict[str, str]]:
    """split_publications → train_model. Return (model, arxiv_id→partition)."""
    raise NotImplementedError("TODO(M3): run_modeling")


def run_predict_all(model: object, partition_map: dict[str, str], labels: dict) -> list[PredictionRow]:
    """Mọi labeled entry của train/valid/test → PredictionRow."""
    raise NotImplementedError("TODO(M3): run_predict_all")


def run_milestone3() -> list[PredictionRow]:
    """
    Entry chính M3.

    Cần code bên trong:
    - track_run('m3')
    - run_labelling, run_modeling, run_predict_all
    - evaluate_split('test', ...)
    - write_predictions_table + export_huggingface_dataset
    """
    raise NotImplementedError("TODO(M3): run_milestone3")
