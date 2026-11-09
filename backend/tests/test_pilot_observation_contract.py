from datetime import datetime, timezone

import pytest

from app.services.pilot_observation_contract import (
    UnverifiedMarketObservation,
    validate_pilot_observation,
)


AS_OF = datetime(2026, 11, 9, tzinfo=timezone.utc)


def valid_bar():
    return {
        "instrument_id": "TEST:MSFT", "symbol": "MSFT",
        "source": "example-provider", "license_reference": "verified-contract-id",
        "license_verified": True, "observation_at": "2026-11-06T21:00:00Z",
        "available_at": "2026-11-06T21:01:00Z",
        "retrieved_at": "2026-11-07T09:00:00Z",
        "currency": "USD", "close": "100.00", "volume": "1000000",
        "adjustment_status": "raw", "bar_status": "closed",
    }


def test_accepts_structurally_complete_bar_without_claiming_live_data():
    bar = valid_bar()
    assert validate_pilot_observation(bar, as_of=AS_OF) == bar


@pytest.mark.parametrize("field,value", [
    ("license_verified", False),
    ("available_at", "2026-11-10T00:00:00Z"),
    ("observation_at", "2026-11-08T10:00:00Z"),
    ("retrieved_at", "2026-11-06T20:00:00Z"),
    ("bar_status", "partial"),
    ("close", "NaN"),
    ("volume", "-1"),
    ("adjustment_status", "unknown"),
    ("license_reference", ""),
])
def test_rejects_unverified_or_invalid_evidence(field, value):
    bar = valid_bar()
    bar[field] = value
    with pytest.raises(UnverifiedMarketObservation):
        validate_pilot_observation(bar, as_of=AS_OF)


def test_rejects_naive_clock():
    with pytest.raises(UnverifiedMarketObservation):
        validate_pilot_observation(valid_bar(), as_of=datetime(2026, 11, 9))
