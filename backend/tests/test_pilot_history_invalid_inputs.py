"""Fail-closed history input contract (synthetic; not operational feed evidence)."""
from datetime import datetime, timezone

import pytest

from app.services.pilot_evidence import EvidenceRejected, validate_pilot_history


NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize("clock", [None, "2026-11-09", 1, datetime(2026, 11, 9)])
def test_invalid_clock_rejected_before_calendar_processing(clock):
    with pytest.raises(EvidenceRejected, match="now must be timezone-aware"):
        validate_pilot_history([], expected_sessions=["2026-11-06"], now=clock)


@pytest.mark.parametrize("calendar", [None, "2026-11-06", [], [None], [42], ["2026-11-06", "2026-11-06"]])
def test_invalid_calendar_fails_closed(calendar):
    with pytest.raises(EvidenceRejected):
        validate_pilot_history([], expected_sessions=calendar, now=NOW)


@pytest.mark.parametrize("bars", [None, {}, "bad", [None], [42], ["bar"]])
def test_invalid_observation_collection_fails_closed(bars):
    with pytest.raises(EvidenceRejected):
        validate_pilot_history(bars, expected_sessions=["2026-11-06"], now=NOW)
