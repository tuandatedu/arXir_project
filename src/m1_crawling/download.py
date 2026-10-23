"""
Download source từng version từ https://export.arxiv.org/src/{id}vN
và extract CHỈ .tex + .bib. Không sửa lệnh figure trong TeX.

Version không có TeX (PDF-only, docx, ...): giữ empty record, KHÔNG drop paper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

ArchiveKind = Literal["targz", "gz", "pdf", "unknown", "empty"]


def source_url(arxiv_id: str, version: int) -> str:
    """
    URL versioned source trên mirror export.

    Cần code bên trong:
    - f"{ARXIV_SRC_MIRROR}/{versioned_id(arxiv_id, version)}"
    - Không dùng arxiv.org.
    """
    raise NotImplementedError("TODO(M1): source_url")


def download_source_archive(
    arxiv_id: str,
    version: int,
    dest_path: Path,
) -> Path:
    """
    Tải archive về dest_path (file tạm, xóa sau khi extract).

    Cần code bên trong:
    - urllib.request hoặc requests, User-Agent mô tả, delay ≥ 3s.
    - arxiv.py 4.x không còn download_source — tự fetch.
    - Ghi nguyên bytes, chưa giải nén.
    """
    raise NotImplementedError("TODO(M1): download_source_archive")


def detect_archive_kind(archive_path: Path) -> ArchiveKind:
    """
    Nhận loại file: gzipped tar, single .gz tex, PDF, ...

    Cần code bên trong:
    - Magic bytes / Content-Type / phần mở rộng.
    - PDF-only → 'pdf' (sẽ thành empty record).
    """
    raise NotImplementedError("TODO(M1): detect_archive_kind")


def extract_tex_and_bib(archive_path: Path, out_dir: Path) -> list[Path]:
    """
    Extract chỉ .tex và .bib vào out_dir. Figure binary / .sty / .pdf KHÔNG vào corpus.

    Cần code bên trong:
    - tarfile / gzip tùy kind.
    - Lọc theo KEPT_SOURCE_SUFFIXES (case-insensitive).
    - Giữ relative path con (paper multi-file thường có folder).
    - KHÔNG đụng nội dung TeX: để nguyên figure env và \\includegraphics.
    - Return danh sách file đã giữ.
    - Nếu không có .tex/.bib: return [] (caller tạo empty record).
    """
    raise NotImplementedError("TODO(M1): extract_tex_and_bib")


def cleanup_temp_archive(archive_path: Path) -> None:
    """Xóa file archive tạm sau khi extract (đề: temp archive deleted)."""
    raise NotImplementedError("TODO(M1): cleanup_temp_archive")
