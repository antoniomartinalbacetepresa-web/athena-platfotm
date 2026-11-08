from datetime import datetime, timezone

from app.services.pilot_market_view import build_pilot_market_view


NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
BAR = {
    "instrumentId": "MSFT", "source": "test-only",
    "licenseRef": "test-only-not-a-license", "usageAuthorized": True,
    "observationAt": "2026-11-06T21:00:00Z",
    "availableAt": "2026-11-06T21:01:00Z",
    "retrievedAt": "2026-11-07T08:00:00Z",
    "currency": "USD", "isFinalBar": True,
    "open": 10.0, "high": 11.0, "low": 9.0,
    "close": 10.5, "volume": 1000,
}


def test_absent_observation_does_not_fabricate_price():
    view = build_pilot_market_view(None, now=NOW)
    assert view["status"] == "unavailable"
    assert view["observation"] is None


def test_validated_bar_preserves_provenance_and_never_enables_orders():
    view = build_pilot_market_view(BAR, now=NOW)
    assert view["status"] == "verified_metadata"
    assert view["observation"]["close"] == 10.5
    assert view["observation"]["licenseRef"] == "test-only-not-a-license"
    assert view["researchOnly"] is True
    assert view["ordersEnabled"] is False


def test_metadata_only_and_unlicensed_bars_are_unavailable():
    for record in (
        {key: value for key, value in BAR.items() if key not in ("open", "high", "low", "close", "volume")},
        {**BAR, "usageAuthorized": False},
        {**BAR, "availableAt": "2026-11-09T00:00:00Z"},
        {**BAR, "close": float("nan")},
    ):
        view = build_pilot_market_view(record, now=NOW)
        assert view["status"] == "unavailable"
        assert view["observation"] is None


def test_expired_bar_is_not_exposed_as_current():
    view = build_pilot_market_view(BAR, now=NOW, max_age_seconds=60)
    assert view["status"] == "unavailable"
    assert view["observation"] is None
