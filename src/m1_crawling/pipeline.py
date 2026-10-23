"""
Orchestrator M1: assigned IDs → working corpus + bảng papers/references + metrics.

Chạy end-to-end (wall-clock = runtime hệ thống) trên Colab CPU-only khi benchmark.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.common.schemas import PaperRow, ReferenceRow


def crawl_one_publication(arxiv_id: str, *, s2_api_key: Optional[str] = None) -> dict:
    """
    Crawl 1 paper: discover → mọi version /src/ → extract tex/bib → S2 refs.

    Cần code bên trong (thứ tự gợi ý):
    1. fetch_paper_by_id + list_versions
    2. save_paper_meta
    3. với mỗi version: download_source_archive, detect_archive_kind,
       extract_tex_and_bib hoặc empty record, cleanup_temp_archive
    4. fetch_s2_references (1 lần / publication, không / version — S2 không phân version)
    5. return dict tóm tắt (n_versions, n_tex, n_refs, errors)

    Tôn trọng ARXIV_MIN_DELAY_SEC và S2_MIN_DELAY_SEC. Một connection tại một thời điểm.
    """
    raise NotImplementedError("TODO(M1): crawl_one_publication")


def run_milestone1(
    ids_file: Path,
    *,
    s2_api_key: Optional[str] = None,
) -> tuple[list[PaperRow], list[ReferenceRow]]:
    """
    Entry chính M1.

    Cần code bên trong:
    - load_assigned_ids
    - track_run('m1') bọc vòng lặp crawl_one_publication
    - ghi tables + metrics
    - lỗi 1 paper: log + tiếp tục (không abort cả range)
    """
    raise NotImplementedError("TODO(M1): run_milestone1")
