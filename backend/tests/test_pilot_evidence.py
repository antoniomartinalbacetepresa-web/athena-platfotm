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
