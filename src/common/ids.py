"""Chuẩn hóa arXiv ID / folder name / version suffix."""

from __future__ import annotations

import re
from typing import Optional

_VERSION_RE = re.compile(r"v(\d+)$")
_NEW_STYLE_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_OLD_STYLE_RE = re.compile(r"^[a-z][a-z.-]*(?:/[a-z][a-z.-]*)?/\d{7}$", re.I)

_URL_PREFIXES = (
    "https://arxiv.org/abs/",
    "http://arxiv.org/abs/",
    "https://export.arxiv.org/abs/",
    "http://export.arxiv.org/abs/",
    "arxiv.org/abs/",
    "www.arxiv.org/abs/",
)


def _strip_prefix(raw: str) -> str:
    text = raw.strip()
    lowered = text.lower()
    for prefix in _URL_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    if lowered.startswith("arxiv:"):
        return text[6:].strip()
    return text


def normalize_arxiv_id(raw: str) -> str:
    """
    Chuẩn hóa ID về dạng canonical: '2310.12345' hoặc scheme cũ 'hep-th/9901001'.

    - Strip, bỏ prefix 'arXiv:', 'https://arxiv.org/abs/', khoảng trắng.
    - Tách suffix version 'vN' (trả về BASE, không kèm vN).
    - Không đổi scheme cũ archive/YYMMNNN.
    """
    if not isinstance(raw, str):
        raise ValueError(f"arXiv ID must be a string, got {type(raw).__name__}")
    text = _strip_prefix(raw)
    # Old-style URLs escape '/' as '%2F'.
    if "%2f" in text.lower():
        import urllib.parse
        text = urllib.parse.unquote(text)
    text = text.strip().strip("/")
    text = _VERSION_RE.sub("", text)
    text = text.strip()
    if not text:
        raise ValueError(f"Empty arXiv ID: {raw!r}")
    if _NEW_STYLE_RE.fullmatch(text) or _OLD_STYLE_RE.fullmatch(text):
        return text
    raise ValueError(f"Invalid arXiv ID: {raw!r}")


def parse_version_suffix(raw: str) -> Optional[int]:
    """
    Lấy số version từ '2310.12345v4' → 4. Base ID không có suffix → None.
    """
    if not isinstance(raw, str):
        return None
    matched = _VERSION_RE.search(raw.strip())
    if not matched:
        return None
    version = int(matched.group(1))
    return version if version >= 1 else None


def folder_name_for_arxiv_id(arxiv_id: str) -> str:
    """
    Folder '2310-12345' cho ID '2310.12345'.
    Scheme cũ 'hep-th/9901001' → 'hep-th_9901001'.
    """
    base = normalize_arxiv_id(arxiv_id)
    if "/" in base:
        return base.replace("/", "_", 1)
    return base.replace(".", "-")


def versioned_id(arxiv_id: str, version: int) -> str:
    """Ghép '2310.12345' + 2 → '2310.12345v2' để gọi /src/."""
    if not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    return f"{normalize_arxiv_id(arxiv_id)}v{version}"


def element_id(arxiv_id: str, discriminant: str) -> str:
    """
    M2: element_id = publication key + '#' + discriminant unique trong publication.
    Ví dụ: element_id('2310.12345', 's1') → '2310-12345#s1'
    """
    if not discriminant or "#" in discriminant:
        raise ValueError("discriminant must be non-empty and must not contain '#'")
    return f"{folder_name_for_arxiv_id(arxiv_id)}#{discriminant}"
