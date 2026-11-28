"""Safe display of market evidence without inventing or leaking unverified prices."""
from datetime import datetime, timezone

from app.services.market_evidence_view import market_evidence_view


NOW = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)
EVIDENCE = {
    "instrumentId": "MSFT:XNAS", "source": "example-provider",
    "license": "research-use", "observationAt": "2026-11-05T21:00:00Z",
    "availableAt": "2026-11-05T21:01:00Z",
    "retrievedAt": "2026-11-05T21:02:00Z", "currency": "USD", "price": 300.0,
}
APPROVAL = {
    **{key: EVIDENCE[key] for key in (
        "instrumentId", "source", "license", "observationAt",
        "availableAt", "retrievedAt", "currency"
    )},
    "licenseVerified": True, "sourceAttributionVerified": True,
    "corporateActionsStatus": "verified", "coverageStatus": "verified",
    "independentReconciliation": True, "price": EVIDENCE["price"],
}


def test_unverified_price_is_hidden():
    view = market_evidence_view(EVIDENCE, now=NOW)
    assert view["price"] is None
    assert view["status"] == "unavailable_unverified"
    assert view["orderExecutionAllowed"] is False
    assert "license_unverified" in view["reasons"]


def test_verified_research_view_preserves_provenance():
    view = market_evidence_view(EVIDENCE, now=NOW, trusted_verification=APPROVAL)
    assert view["price"] == 300.0
    assert view["ageSeconds"] == 82800
    assert view["source"] == "example-provider"
    assert view["status"] == "verified_research"


def test_replayed_approval_cannot_expose_different_snapshot():
    altered = dict(EVIDENCE, currency="EUR")
    view = market_evidence_view(altered, now=NOW, trusted_verification=APPROVAL)
    assert view["price"] is None
    assert "verification_currency_mismatch" in view["reasons"]


def test_nonfinite_and_boolean_prices_never_display():
    for price in (float("nan"), float("inf"), -1, True, 0):
        view = market_evidence_view(dict(EVIDENCE, price=price), now=NOW, trusted_verification=APPROVAL)
        assert view["price"] is None


def test_verified_metadata_cannot_authorize_substituted_price():
    altered = dict(EVIDENCE, price=999.0)
    view = market_evidence_view(altered, now=NOW, trusted_verification=APPROVAL)
    assert view["price"] is None
    assert view["status"] == "unavailable_unverified"
    assert "price_unverified" in view["reasons"]


def test_missing_price_binding_cannot_claim_verified_research():
    approval = dict(APPROVAL)
    approval.pop("price")
    view = market_evidence_view(EVIDENCE, now=NOW, trusted_verification=approval)
    assert view["price"] is None
    assert view["status"] == "unavailable_unverified"
    assert "price_unverified" in view["reasons"]


def test_future_observation_has_no_misleading_zero_age():
    future = dict(EVIDENCE, observationAt="2026-11-07T21:00:00Z")
    view = market_evidence_view(future, now=NOW, trusted_verification=APPROVAL)
    assert view["price"] is None
    assert view["ageSeconds"] is None
    assert view["status"] == "unavailable_unverified"
    assert "future_market_evidence" in view["reasons"]


def test_invalid_observation_does_not_claim_freshness():
    invalid = dict(EVIDENCE, observationAt="not-a-timestamp")
    view = market_evidence_view(invalid, now=NOW, trusted_verification=APPROVAL)
    assert view["ageSeconds"] is None
    assert view["price"] is None
    assert "invalid_timestamps" in view["reasons"]
