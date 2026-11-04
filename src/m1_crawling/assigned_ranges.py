"""Assigned arXiv ID ranges for Milestone 1.

Each endpoint comes from the team's assignment spreadsheet. For a range that
crosses a month boundary, ``cross_month_limit`` is the last serial number of
the *first* month and MUST be checked against the arXiv archive. The spreadsheet
alone does not establish that number.

No fixed number of IDs per student is assumed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignedRange:
    number: int
    first: str
    last: str
    cross_month_limit: int | None = None


# Endpoints match the five rows in the team's assignment spreadsheet.
# WARNING: 40363 and 31045 are existing provisional month-end values;
# verify them before a full crawl. They are NOT given by the spreadsheet.
RANGES: tuple[AssignedRange, ...] = (
    AssignedRange(1, "2609.37834", "2610.02470", cross_month_limit=40363),
    AssignedRange(2, "2604.15535", "2604.20534"),
    AssignedRange(3, "2604.00535", "2604.05534"),
    AssignedRange(4, "2603.25580", "2604.00534", cross_month_limit=30045),
    AssignedRange(5, "2603.15580", "2603.20579"),
)


def _parse_id(arxiv_id: str) -> tuple[str, int]:
    """Return (YYMM, serial) after validating the modern arXiv ID format."""
    parts = arxiv_id.split(".")
    if len(parts) != 2:
        raise ValueError(f"Invalid arXiv ID: {arxiv_id!r}")

    month, serial = parts
    if (len(month) != 4 or not month.isdigit() or
            len(serial) != 5 or not serial.isdigit() or
            not 1 <= int(month[2:]) <= 12 or
            not 1 <= int(serial) <= 99999):
        raise ValueError(f"Invalid arXiv ID: {arxiv_id!r}")
    return month, int(serial)


def _next_month(yymm: str) -> str:
    year, month = int(yymm[:2]), int(yymm[2:])
    if month == 12:
        return f"{year + 1:02d}01"
    return f"{year:02d}{month + 1:02d}"


def range_ids(item: AssignedRange) -> list[str]:
    """Expand one assigned range, with no fixed size requirement."""
    first_month, start = _parse_id(item.first)
    last_month, end = _parse_id(item.last)

    if first_month == last_month:
        if start > end:
            raise ValueError(f"Range {item.number}: first ID is after last ID")
        numbers = [f"{first_month}.{n:05d}" for n in range(start, end + 1)]
    else:
        if last_month != _next_month(first_month):
            raise ValueError(f"Range {item.number}: unsupported month span")
        limit = item.cross_month_limit
        if limit is None:
            raise ValueError(f"Range {item.number}: cross-month limit must be verified")
        if not start <= limit <= 99999:
            raise ValueError(f"Range {item.number}: invalid cross-month limit {limit}")

        numbers = (
            [f"{first_month}.{n:05d}" for n in range(start, limit + 1)]
            + [f"{last_month}.{n:05d}" for n in range(1, end + 1)]
        )

    if not numbers:
        raise ValueError(f"Range {item.number} is empty")
    if len(numbers) != len(set(numbers)):
        raise ValueError(f"Range {item.number} contains duplicate IDs")
    return numbers


def assigned_ids(range_number: int = 0) -> list[str]:
    """Return all IDs (0) or IDs for one member (1..5)."""
    if range_number != 0 and range_number not in {item.number for item in RANGES}:
        raise ValueError(f"Unknown range number: {range_number}")

    ids: list[str] = []
    for item in RANGES:
        if range_number in (0, item.number):
            ids.extend(range_ids(item))

    if len(ids) != len(set(ids)):
        raise ValueError("Overlapping assigned ranges")
    return ids


if __name__ == "__main__":
    for item in RANGES:
        print(f"Range {item.number}: {item.first} -> {item.last}: {len(range_ids(item))} IDs")
    print(f"Total: {len(assigned_ids())} IDs")
