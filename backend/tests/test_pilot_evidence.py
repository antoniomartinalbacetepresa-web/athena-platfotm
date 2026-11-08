from datetime import datetime, timezone

import pytest

from app.services.pilot_evidence import EvidenceRejected, validate_pilot_observation


NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
BASE = dict(
    instrumentId="MSFT", source="pilot", licenseRef="contract-reviewed",
    usageAuthorized=True, observationAt="2026-11-06T21:00:00Z",
    availableAt="2026-11-06T21:01:00Z",
    retrievedAt="2026-11-07T08:00:00Z",
    currency="USD", isFinalBar=True,
)


def test_accepts_pit_order_and_returns_age():
    result = validate_pilot_observation(BASE, now=NOW)
    assert result["ageSeconds"] > 0
    assert result["availableAt"].endswith("+00:00")


@pytest.mark.parametrize("change", [
    {"usageAuthorized": False}, {"licenseRef": ""}, {"isFinalBar": False},
    {"availableAt": "2026-11-09T00:00:00Z"},
    {"retrievedAt": "2026-11-05T00:00:00Z"},
    {"observationAt": "2026-11-06T21:00:00"}, {"currency": ""},
])
def test_rejects_untrusted_observations(change):
    with pytest.raises(EvidenceRejected):
        validate_pilot_observation({**BASE, **change}, now=NOW)


def test_freshness_threshold_is_inclusive_and_rejects_stale_data():
    age = validate_pilot_observation(BASE, now=NOW)["ageSeconds"]
    assert validate_pilot_observation(BASE, now=NOW, max_age_seconds=age)["ageSeconds"] == age
    with pytest.raises(EvidenceRejected, match="exceeds permitted age"):
        validate_pilot_observation(BASE, now=NOW, max_age_seconds=age - 1)


@pytest.mark.parametrize("threshold", [-1, True, 1.5, "3600"])
def test_invalid_freshness_threshold_fails_closed(threshold):
    with pytest.raises(EvidenceRejected, match="invalid maximum observation age"):
        validate_pilot_observation(BASE, now=NOW, max_age_seconds=threshold)


def test_subsecond_staleness_cannot_bypass_zero_age_limit():
    from datetime import timedelta

    observed_now = datetime(2026, 11, 8, tzinfo=timezone.utc)
    record = {**BASE,
              "observationAt": (observed_now - timedelta(milliseconds=500)).isoformat(),
              "availableAt": (observed_now - timedelta(milliseconds=500)).isoformat(),
              "retrievedAt": (observed_now - timedelta(milliseconds=250)).isoformat()}
    with pytest.raises(EvidenceRejected, match="exceeds permitted age"):
        validate_pilot_observation(record, now=observed_now, max_age_seconds=0)


def test_old_market_observation_cannot_be_refreshed_by_late_publication():
    record = {**BASE,
              "observationAt": "2026-10-01T20:00:00Z",
              "availableAt": "2026-11-07T23:58:00Z",
              "retrievedAt": "2026-11-07T23:59:00Z"}
    with pytest.raises(EvidenceRejected, match="exceeds permitted age"):
        validate_pilot_observation(record, now=NOW, max_age_seconds=3600)


def test_freshness_age_reports_observation_age_not_ingestion_age():
    record = {**BASE, "retrievedAt": "2026-11-07T23:59:00Z"}
    result = validate_pilot_observation(record, now=NOW)
    expected = int((NOW - datetime.fromisoformat("2026-11-06T21:00:00+00:00")).total_seconds())
    assert result["ageSeconds"] == expected


@pytest.mark.parametrize("bad_bar", [
    {"close": float("nan")}, {"close": float("inf")}, {"close": 0},
    {"close": -1}, {"close": True}, {"volume": -1},
    {"volume": 1.5}, {"volume": True},
    {"open": 10, "high": 9, "low": 8, "close": 11},
])
def test_rejects_nonfinite_or_inconsistent_market_bars(bad_bar):
    with pytest.raises(EvidenceRejected):
        validate_pilot_observation({**BASE, **bad_bar}, now=NOW)


def test_accepts_consistent_closed_ohlcv_bar():
    record = {**BASE, "open": 10.0, "high": 11.0, "low": 9.0,
              "close": 10.5, "volume": 1000}
    assert validate_pilot_observation(record, now=NOW)["isFinalBar"] is True
