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
    view = build_pilot_market_view(BAR, now=NOW, rights_reviewed=True)
    assert view["status"] == "verified_metadata"
    assert view["reason"] == "rights_attested_metadata_only_not_operationally_verified"
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
        view = build_pilot_market_view(record, now=NOW, rights_reviewed=True)
        assert view["status"] == "unavailable"
        assert view["observation"] is None


def test_expired_bar_is_not_exposed_as_current():
    view = build_pilot_market_view(BAR, now=NOW, max_age_seconds=60, rights_reviewed=True)
    assert view["status"] == "unavailable"
    assert view["observation"] is None


def test_provider_self_attestation_cannot_bypass_independent_rights_review():
    view = build_pilot_market_view(BAR, now=NOW)
    assert view == {
        "status": "unavailable",
        "reason": "independent_rights_review_required",
        "observation": None,
    }
    assert build_pilot_market_view(BAR, now=NOW, rights_reviewed=1)["observation"] is None


def test_invalid_clock_and_freshness_policy_fail_closed_without_exposing_bar():
    for threshold in (-1, True, 1.5, "3600"):
        view = build_pilot_market_view(BAR, now=NOW, rights_reviewed=True, max_age_seconds=threshold)
        assert view == {"status": "unavailable", "reason": "invalid_freshness_policy", "observation": None}

    naive_now = NOW.replace(tzinfo=None)
    view = build_pilot_market_view(BAR, now=naive_now, rights_reviewed=True)
    assert view == {"status": "unavailable", "reason": "invalid_research_clock", "observation": None}


def test_malformed_research_clock_types_fail_closed():
    for invalid_now in (None, "2026-11-08T00:00:00Z", 0, object()):
        view = build_pilot_market_view(BAR, now=invalid_now, rights_reviewed=True)
        assert view == {
            "status": "unavailable",
            "reason": "invalid_research_clock",
            "observation": None,
        }
