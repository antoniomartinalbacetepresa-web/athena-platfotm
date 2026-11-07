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
