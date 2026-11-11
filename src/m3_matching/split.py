"""
Split THEO PUBLICATION (không phải theo entry hay cặp):

- test:  1 paper manual + 1 paper auto
- valid: 1 paper manual + 1 paper auto
- train: toàn bộ phần còn lại của labeled pool (cả manual và auto)

Chỉ publication trong 3 split này mới tham gia huấn luyện và đánh giá.
Đảm bảo seed để tái lập hoàn toàn (reproducible).
"""

from __future__ import annotations

import random
from typing import Any, Literal

Partition = Literal["train", "valid", "test"]


def split_publications(
    labels: dict[str, list[dict[str, Any]]],
    *,
    seed: int = 42,
    k: int = 1,
) -> dict[str, Partition]:
    """
    Phân chia các bài báo đã gán nhãn thành 3 tập train, valid, test:
    - Nhóm k thành viên:
      + Test: k bài manual + k bài auto (mặc định k=1: 1+1, k=2: 2+2)
      + Valid: k bài manual + k bài auto
      + Train: tất cả các bài còn lại đã gán nhãn
    - Bài không được gán nhãn -> không nằm trong kết quả trả về.
    """
    manual_ids: list[str] = []
    auto_ids: list[str] = []

    for arxiv_id, entries in sorted(labels.items()):
        if not entries:
            continue
        is_manual = any(e.get("source") == "manual" for e in entries)
        if is_manual:
            manual_ids.append(arxiv_id)
        else:
            auto_ids.append(arxiv_id)

    # Cần 2*k cho test + 2*k cho valid = 4*k tổng cho cả auto lẫn manual
    needed_per_set = 2 * k
    needed_total_manual = needed_per_set * 2
    needed_total_auto = needed_per_set * 2
    
    if len(manual_ids) < needed_total_manual:
        raise ValueError(
            f"Cần tối thiểu {needed_total_manual} bài báo manual để chia valid và test (k={k}, hiện có: {len(manual_ids)})."
        )
    if len(auto_ids) < needed_total_auto:
        raise ValueError(
            f"Cần tối thiểu {needed_total_auto} bài báo auto để chia valid và test (k={k}, hiện có: {len(auto_ids)})."
        )

    # Dùng deterministic RNG với seed cố định
    rng = random.Random(seed)
    shuffled_manual = list(manual_ids)
    shuffled_auto = list(auto_ids)
    rng.shuffle(shuffled_manual)
    rng.shuffle(shuffled_auto)

    partition_map: dict[str, Partition] = {}

    # Test: k manual + k auto
    for _ in range(k):
        partition_map[shuffled_manual.pop(0)] = "test"
        partition_map[shuffled_auto.pop(0)] = "test"

    # Valid: k manual + k auto
    for _ in range(k):
        partition_map[shuffled_manual.pop(0)] = "valid"
        partition_map[shuffled_auto.pop(0)] = "valid"

    # Train: Toàn bộ còn lại
    for pid in shuffled_manual:
        partition_map[pid] = "train"
    for pid in shuffled_auto:
        partition_map[pid] = "train"

    return partition_map
