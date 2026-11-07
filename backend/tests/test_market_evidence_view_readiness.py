"""Market evidence display cannot promote unverified price to verified readiness."""
from datetime import datetime, timedelta, timezone

from app.services.market_evidence_view import market_evidence_view


NOW = datetime(2026, 11, 7, 9, tzinfo=timezone.utc)


def _payload():
    return {
        "instrumentId": "MSFT:XNAS",
        "source": "test-provider",
        "license": "test-only-not-a-real-data-license",
        "observationAt": "2026-11-06T21:00:00Z",
        "availableAt": "2026-11-06T21:01:00Z",
        "retrievedAt": "2026-11-06T21:02:00Z",
        "currency": "USD",
        "price": 100.0,
    }


def _verification(payload):
    return {
        **payload,
        "licenseVerified": True,
        "sourceAttributionVerified": True,
        "corporateActionsStatus": "verified",
        "coverageStatus": "verified",
        "independentReconciliation": True,
    }


def test_verified_metadata_and_price_are_exposed_only_together():
    payload = _payload()
    view = market_evidence_view(payload, now=NOW, trusted_verification=_verification(payload))
    assert view["status"] == "verified_research"
    assert view["price"] == 100.0
    assert view["licenseVerified"] is True
    assert view["coverageStatus"] == "verified"
    assert view["corporateActionsStatus"] == "verified"
    assert view["independentReconciliation"] is True
    assert view["orderExecutionAllowed"] is False


def test_verified_header_does_not_authorize_changed_price():
    payload = _payload()
    verified = _verification(payload)
    payload["price"] = 101.0
    view = market_evidence_view(payload, now=NOW, trusted_verification=verified)
    assert view["status"] == "unavailable_unverified"
    assert view["price"] is None
    assert "price_unverified" in view["reasons"]
    assert view["licenseVerified"] is False
    assert view["coverageStatus"] == "unverified"
    assert view["corporateActionsStatus"] == "unverified"
    assert view["independentReconciliation"] is False


def test_provider_claims_cannot_replace_independent_verification():
    payload = _payload()
    payload.update(licenseVerified=True, coverageStatus="verified", independentReconciliation=True)
    view = market_evidence_view(payload, now=NOW)
    assert view["status"] == "unavailable_unverified"
    assert view["price"] is None
    assert view["licenseVerified"] is False
    assert view["coverageStatus"] == "unverified"


def test_stale_price_does_not_appear_as_verified():
    payload = _payload()
    view = market_evidence_view(
        payload, now=NOW + timedelta(days=4), trusted_verification=_verification(payload)
    )
    assert "stale_observation" in view["reasons"]
    assert view["price"] is None
    assert view["licenseVerified"] is False


def test_extremely_large_integer_price_fails_closed_without_server_error():
    payload = _payload()
    verified = _verification(payload)
    payload["price"] = 10 ** 1000
    verified["price"] = 10 ** 1000
    view = market_evidence_view(payload, now=NOW, trusted_verification=verified)
    assert view["price"] is None
    assert view["priceStatus"] == "unavailable_unverified"
    assert "price_unverified" in view["reasons"]


def test_price_status_explicit_for_verified_and_mismatched_quotes():
    payload = _payload()
    verified = _verification(payload)
    assert market_evidence_view(payload, now=NOW, trusted_verification=verified)["priceStatus"] == "verified"
    payload["price"] = 101.0
    assert market_evidence_view(payload, now=NOW, trusted_verification=verified)["priceStatus"] == "unavailable_unverified"


def test_staleness_status_is_explicit_at_freshness_boundary():
    payload = _payload()
    verified = _verification(payload)
    observed = datetime.fromisoformat(payload["observationAt"].replace("Z", "+00:00"))
    fresh = market_evidence_view(payload, now=observed + timedelta(days=2), trusted_verification=verified)
    stale = market_evidence_view(payload, now=observed + timedelta(days=2, seconds=1), trusted_verification=verified)
    assert fresh["stalenessStatus"] == "fresh"
    assert fresh["priceStatus"] == "verified"
    assert stale["stalenessStatus"] == "stale"
    assert stale["price"] is None
    assert stale["priceStatus"] == "unavailable_unverified"


def test_invalid_observation_has_unknown_staleness_not_fresh():
    payload = _payload()
    verified = _verification(payload)
    payload["observationAt"] = "invalid"
    view = market_evidence_view(payload, now=NOW, trusted_verification=verified)
    assert view["stalenessStatus"] == "unknown"
    assert view["ageSeconds"] is None
    assert view["price"] is None


def test_fractional_second_past_freshness_limit_is_stale():
    payload = _payload()
    observed = datetime.fromisoformat(payload["observationAt"].replace("Z", "+00:00"))
    view = market_evidence_view(
        payload,
        now=observed + timedelta(days=2, microseconds=1),
        trusted_verification=_verification(payload),
    )
    assert view["stalenessStatus"] == "stale"
    assert view["ageSeconds"] > timedelta(days=2).total_seconds()
    assert view["price"] is None
    assert "stale_observation" in view["reasons"]


def test_recent_quote_with_future_retrieval_is_invalid_not_fresh():
    payload = _payload()
    payload["retrievedAt"] = (NOW + timedelta(minutes=1)).isoformat()
    view = market_evidence_view(payload, now=NOW, trusted_verification=_verification(payload))
    assert view["stalenessStatus"] == "invalid"
    assert view["price"] is None
    assert "future_retrieval" in view["reasons"]


def test_recent_quote_with_impossible_pit_order_is_invalid():
    payload = _payload()
    payload["availableAt"] = "2026-11-06T20:00:00Z"
    view = market_evidence_view(payload, now=NOW, trusted_verification=_verification(payload))
    assert view["stalenessStatus"] == "invalid"
    assert view["priceStatus"] == "unavailable_unverified"
    assert "invalid_pit_order" in view["reasons"]
