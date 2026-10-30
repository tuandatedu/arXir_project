
"""Các hàm hỗ trợ chuẩn hóa arXiv ID và tạo khóa định danh ổn định."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlparse


# Regex nhận diện arXiv ID dạng mới, ví dụ: 2310.12345.
# ID gồm 4 chữ số, dấu chấm và 4 hoặc 5 chữ số.
NEW_STYLE = re.compile(r"^\d{4}\.\d{4,5}$")

# Regex nhận diện arXiv ID dạng cũ, ví dụ: hep-th/9901001.
# Phần trước dấu '/' là mã lĩnh vực, phần sau gồm 7 chữ số.
OLD_STYLE = re.compile(r"^[A-Za-z][A-Za-z.-]+/\d{7}$")

# Regex nhận diện hậu tố version ở cuối ID, ví dụ: v1, v2, v10.
VERSION = re.compile(r"v(\d+)$", re.IGNORECASE)


def _identifier_text(raw: str) -> str:
    """Loại bỏ URL và tiền tố phổ biến, chỉ giữ lại phần arXiv ID."""

    # Kiểm tra kiểu dữ liệu đầu vào để tránh lỗi khi xử lý chuỗi.
    if not isinstance(raw, str):
        raise TypeError("arXiv ID must be a string")

    # Loại bỏ khoảng trắng thừa ở đầu và cuối chuỗi.
    value = raw.strip()

    # Loại bỏ tiền tố arXiv: nếu người dùng nhập theo dạng này.
    if value.lower().startswith("arxiv:"):
        value = value[6:].strip()

    # Nếu đầu vào là URL HTTP hoặc HTTPS, lấy phần cuối của đường dẫn.
    if value.lower().startswith(("http://", "https://")):

        # Phân tích URL, lấy path và loại bỏ dấu '/' ở cuối.
        # Sau đó lấy thành phần cuối cùng trong đường dẫn.
        value = unquote(urlparse(value).path.rstrip("/").rsplit("/", 1)[-1])

    # Trả về ID sau khi loại bỏ khoảng trắng còn lại.
    return value.strip()


def parse_version_suffix(raw: str) -> Optional[int]:
    """Trích xuất số version ở cuối ID; trả về None nếu không có."""

    # Chuẩn hóa đầu vào trước khi tìm hậu tố version.
    value = _identifier_text(raw)

    # Tìm hậu tố có dạng vN ở cuối chuỗi.
    match = VERSION.search(value)

    # Chuyển phần số thành int nếu tìm thấy, ngược lại trả về None.
    return int(match.group(1)) if match else None


def normalize_arxiv_id(raw: str) -> str:
    """Trả về arXiv ID chuẩn, không bao gồm hậu tố version."""

    # Loại bỏ URL, tiền tố và các thành phần không cần thiết.
    value = _identifier_text(raw)

    # Loại bỏ hậu tố version, ví dụ 2310.12345v2 → 2310.12345.
    value = VERSION.sub("", value)

    # Chỉ chấp nhận ID thuộc một trong hai định dạng hợp lệ.
    if NEW_STYLE.fullmatch(value) or OLD_STYLE.fullmatch(value):
        return value

    # Báo lỗi nếu ID không đúng định dạng được hỗ trợ.
    raise ValueError(f"Invalid arXiv ID: {raw!r}")


def folder_name_for_arxiv_id(arxiv_id: str) -> str:
    """Chuyển arXiv ID thành tên thư mục an toàn trên filesystem."""

    # Chuẩn hóa ID trước để URL và ID có version cùng trỏ đến một thư mục.
    value = normalize_arxiv_id(arxiv_id)

    # Thay các ký tự đặc biệt trong ID bằng dấu '-' hoặc '_'.
    # Ví dụ: 2310.12345 → 2310-12345.
    # Ví dụ: hep-th/9901001 → hep-th_9901001.
    return value.replace(".", "-").replace("/", "_")


def versioned_id(arxiv_id: str, version: int) -> str:
    """Tạo arXiv ID có hậu tố version từ một ID gốc."""

    # Kiểm tra version phải là số nguyên dương.
    # bool là lớp con của int trong Python nên cần loại trừ riêng.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")

    # Chuẩn hóa ID gốc rồi nối hậu tố version.
    # Ví dụ: 2310.12345 + 2 → 2310.12345v2.
    return f"{normalize_arxiv_id(arxiv_id)}v{version}"


def element_id(arxiv_id: str, discriminant: str) -> str:
    """Tạo khóa element ổn định dùng trong các bảng dữ liệu M2."""

    # Chuyển discriminant thành chuỗi và loại bỏ khoảng trắng thừa.
    key = str(discriminant).strip()

    # Discriminant không được rỗng hoặc chứa '#',
    # vì ký tự này được dùng để phân tách arXiv ID và element key.
    if not key or "#" in key:
        raise ValueError("discriminant must be non-empty and must not contain '#'")

    # Kết hợp tên thư mục của publication với discriminant.
    # Ví dụ: 2310.12345 và s1 → 2310-12345#s1.
    return f"{folder_name_for_arxiv_id(arxiv_id)}#{key}"
