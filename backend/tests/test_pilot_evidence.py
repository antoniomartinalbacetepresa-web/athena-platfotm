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
