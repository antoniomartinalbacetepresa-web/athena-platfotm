from datetime import datetime, timedelta, timezone

import pytest

from app.services.pilot_market_evidence import EvidenceRejected, validate_daily_price_evidence


NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def sample():
    return {
        "instrumentId": "NASDAQ:MSFT", "symbol": "MSFT",
        "source": "licensed-provider", "licenseId": "contract-123",
        "usageAuthorized": True, "observationAt": NOW - timedelta(days=2),
        "availableAt": NOW - timedelta(days=1),
        "retrievedAt": NOW, "currency": "USD",
        "adjustmentPolicy": "raw", "close": "100.25",
    }


def test_accepts_explicit_authorized_pit_metadata():
    item = sample()
    assert validate_daily_price_evidence(item, as_of=NOW) == item


@pytest.mark.parametrize("field,value", [
    ("usageAuthorized", False),
    ("licenseId", ""),
    ("licenseId", "contract-123\nforged"),
    ("source", "provider\x00injected"),
    ("instrumentId", "NASDAQ:MSFT\rforged"),
    ("currency", "USD\x7f"),
    ("close", True),
    ("adjustmentPolicy", "unknown"),
    ("close", "NaN"),
    ("close", "-1"),
    ("availableAt", NOW + timedelta(days=1)),
    ("retrievedAt", NOW + timedelta(days=1)),
    ("observationAt", NOW + timedelta(days=1)),
    ("currency", None),
])
def test_rejects_unsafe_evidence(field, value):
    item = sample()
    item[field] = value
    with pytest.raises(EvidenceRejected):
        validate_daily_price_evidence(item, as_of=NOW)


def test_rejects_naive_clock_and_unverified_licensing():
    with pytest.raises(EvidenceRejected):
        validate_daily_price_evidence(sample(), as_of=NOW.replace(tzinfo=None))
    item = sample()
    del item["usageAuthorized"]
    with pytest.raises(EvidenceRejected):
        validate_daily_price_evidence(item, as_of=NOW)

def test_accepts_authorized_daily_share_volume():
    item = sample()
    item.update(volume=123456, volumeUnit="shares")
    assert validate_daily_price_evidence(item, as_of=NOW)["volume"] == 123456


@pytest.mark.parametrize("volume,unit", [
    (-1, "shares"), (True, "shares"), (1.5, "shares"),
    ("123", "shares"), (None, "shares"), (100, "contracts"),
    (100, None),
])
def test_rejects_invalid_or_unattributed_volume(volume, unit):
    item = sample()
    item.update(volume=volume, volumeUnit=unit)
    with pytest.raises(EvidenceRejected):
        validate_daily_price_evidence(item, as_of=NOW)


def test_rejects_volume_unit_without_volume():
    item = sample()
    item["volumeUnit"] = "shares"
    with pytest.raises(EvidenceRejected):
        validate_daily_price_evidence(item, as_of=NOW)
