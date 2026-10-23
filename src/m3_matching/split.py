"""
Split THEO PUBLICATION (không phải theo entry):

- test:  1 manual + 1 auto
- valid: 1 manual + 1 auto
- train: phần còn lại của labeled pool

Chỉ publication trong 3 split mới có hàng ở bảng predictions.
"""

from __future__ import annotations

from typing import Any, Literal

Partition = Literal["train", "valid", "test"]


def split_publications(
    labels: dict[str, list[dict[str, Any]]],
    *,
    seed: int = 42,
) -> dict[str, Partition]:
    """
    Map arxiv_id → partition.

    Cần code bên trong:
    - Tách manual vs auto theo field source
    - Chọn 1+1 test, 1+1 valid (đủ paper); seed để reproduce
    - Paper unlabeled → không vào map
    """
    raise NotImplementedError("TODO(M3): split_publications")
