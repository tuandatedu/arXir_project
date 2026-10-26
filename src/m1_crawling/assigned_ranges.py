"""Five assigned intervals transcribed from the team spreadsheet screenshot.

CROSS-MONTH endpoints 2603.31045 and 2609.40363 are *inferred* using the
assumption that each student's allocation contains exactly 5000 papers.
This must be confirmed with `--verify-boundaries` before a full crawl; the
screenshot itself does not explicitly give the last ID of either month.
No student names or IDs are stored here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignedRange:
    number: int
    first: str
    last: str
    cross_month_limit: int | None = None


RANGES = (
    AssignedRange(1, "2609.37834", "2610.02470", 40363),
    AssignedRange(2, "2604.15535", "2604.20534"),
    AssignedRange(3, "2604.00535", "2604.05534"),
    AssignedRange(4, "2603.26580", "2604.00534", 31045),
    AssignedRange(5, "2603.15580", "2603.20579"),
)


def range_ids(item: AssignedRange) -> list[str]:
    first_month, start = item.first.split(".")
    last_month, end = item.last.split(".")
    if first_month == last_month:
        numbers = [f"{first_month}.{n:05d}" for n in range(int(start), int(end) + 1)]
    else:
        if item.cross_month_limit is None:
            raise ValueError("Cross-month limit must be verified")
        numbers = ([f"{first_month}.{n:05d}" for n in range(int(start), item.cross_month_limit + 1)] +
                   [f"{last_month}.{n:05d}" for n in range(1, int(end) + 1)])
    if len(numbers) != 5000:
        raise ValueError(f"Range {item.number} has {len(numbers)} IDs, expected 5000")
    return numbers


def assigned_ids(range_number: int = 0) -> list[str]:
    ids: list[str] = []
    for item in RANGES:
        if range_number in (0, item.number):
            ids.extend(range_ids(item))
    if len(ids) != len(set(ids)):
        raise ValueError("Overlapping assigned ranges")
    return ids
