from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import combinations
from random import Random

import pytest

from app.services.research_oos_overlap import count_overlapping_period_pairs


_ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _window(start: int, end: int) -> tuple[datetime, datetime]:
    return (_ORIGIN + timedelta(days=start), _ORIGIN + timedelta(days=end))


def test_touching_boundaries_do_not_overlap_but_nested_and_equal_windows_do() -> None:
    periods = [_window(0, 10), _window(2, 4), _window(4, 10), _window(10, 12)]
    # (0,10) overlaps (2,4) and (4,10); (2,4) only touches (4,10).
    assert count_overlapping_period_pairs(periods) == 2
    assert count_overlapping_period_pairs([_window(0, 2), _window(0, 2)]) == 1


def test_sweep_matches_independent_pairwise_oracle_for_random_windows() -> None:
    random = Random(13)
    for count in range(1, 45):
        periods = []
        for _ in range(count):
            start = random.randrange(30)
            periods.append(_window(start, start + random.randrange(1, 10)))
        expected = sum(
            max(left[0], right[0]) < min(left[1], right[1])
            for left, right in combinations(periods, 2)
        )
        assert count_overlapping_period_pairs(periods) == expected


def test_large_fully_overlapping_cohort_is_counted_without_pairwise_scan() -> None:
    assert count_overlapping_period_pairs([_window(0, 30)] * 5000) == 12_497_500


def test_nonpositive_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="duración positiva"):
        count_overlapping_period_pairs([_window(2, 2)])
