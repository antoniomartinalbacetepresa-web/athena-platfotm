from __future__ import annotations

"""Efficient strict-overlap diagnostics for longitudinal OOS evaluation periods."""

from datetime import datetime
import heapq
from typing import Sequence


def count_overlapping_period_pairs(periods: Sequence[tuple[datetime, datetime]]) -> int:
    """Count unordered pairs whose evaluation windows intersect for positive time.

    Caller-provided timestamps must be comparable and timezone-aware. Touching
    boundaries are not overlaps. A min-heap of active end times makes the
    computation O(n log n) instead of comparing every pair of observations.
    """
    active_ends: list[datetime] = []
    pairs = 0
    for start, end in sorted(periods, key=lambda period: (period[0], period[1])):
        if end <= start:
            raise ValueError("Los periodos OOS deben tener duración positiva.")
        while active_ends and active_ends[0] <= start:
            heapq.heappop(active_ends)
        pairs += len(active_ends)
        heapq.heappush(active_ends, end)
    return pairs
