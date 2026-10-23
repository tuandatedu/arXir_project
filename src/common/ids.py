"""Chuẩn hóa arXiv ID / folder name / version suffix."""

from __future__ import annotations

from typing import Optional


def normalize_arxiv_id(raw: str) -> str:
    """
    Chuẩn hóa ID về dạng canonical: '2310.12345' hoặc scheme cũ 'hep-th/9901001'.

    Cần code bên trong:
    - Strip, bỏ prefix 'arXiv:', 'https://arxiv.org/abs/', khoảng trắng.
    - Tách suffix version 'vN' ra khỏi base ID (hàm này trả về BASE, không kèm vN).
    - Không đổi scheme cũ archive/YYMMNNN.
    """
    raise NotImplementedError("TODO(common): normalize_arxiv_id")


def parse_version_suffix(raw: str) -> Optional[int]:
    """
    Lấy số version từ '2310.12345v4' → 4. Base ID không có suffix → None.

    Cần code bên trong:
    - Regex r'v(\\d+)$'.
    - Trả None nếu không có suffix (caller tự hiểu là latest hoặc v1).
    """
    raise NotImplementedError("TODO(common): parse_version_suffix")


def folder_name_for_arxiv_id(arxiv_id: str) -> str:
    """
    Đề gợi ý: folder '2310-12345' cho ID '2310.12345'.

    Cần code bên trong:
    - Thay '.' bằng '-'.
    - Scheme cũ 'hep-th/9901001' → thay '/' cho hợp filesystem, ví dụ 'hep-th_9901001'.
    """
    raise NotImplementedError("TODO(common): folder_name_for_arxiv_id")


def versioned_id(arxiv_id: str, version: int) -> str:
    """Ghép '2310.12345' + 2 → '2310.12345v2' để gọi /src/."""
    raise NotImplementedError("TODO(common): versioned_id")


def element_id(arxiv_id: str, discriminant: str) -> str:
    """
    M2: element_id = publication key + '#' + discriminant unique trong publication.
    Ví dụ: element_id('2310.12345', 's1') → '2310-12345#s1'
    """
    raise NotImplementedError("TODO(common): element_id")
