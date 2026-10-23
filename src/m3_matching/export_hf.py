"""
Publish 6 bảng Parquet sharded + dataset card.

Layout:
  data/hf_dataset/README.md   # YAML configs (không custom loading script)
  data/hf_dataset/data/{papers,references,elements,hierarchy,bibtex,predictions}/*.parquet

Cột PHẲNG: list[str] một cấp OK; cấm nested object / JSON blob.
"""

from __future__ import annotations

from pathlib import Path


def write_dataset_card(export_dir: Path) -> Path:
    """
    README.md YAML:

    ---
    configs:
    - config_name: papers
      data_files:
      - split: train
        path: data/papers/*.parquet
    - ... một config / bảng ...
    ---
    """
    raise NotImplementedError("TODO(M3): write_dataset_card")


def export_table(name: str, rows: list[dict], export_dir: Path, shard_size: int = 5000) -> None:
    """Chia rows thành data/{name}/part-000.parquet, ..."""
    raise NotImplementedError("TODO(M3): export_table")


def export_huggingface_dataset() -> Path:
    """
    Đọc 6 jsonl từ data/tables, ghi Parquet + card.

    Cần code bên trong:
    - papers, references (M1), elements, hierarchy, bibtex (M2), predictions (M3)
    - predictions chỉ chứa labeled split papers
    - return HF_EXPORT_DIR — nhóm upload Hub theo hướng dẫn Lab Instructors
    """
    raise NotImplementedError("TODO(M3): export_huggingface_dataset")
