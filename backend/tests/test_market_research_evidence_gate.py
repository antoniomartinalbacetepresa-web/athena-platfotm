"""Regression tests for the fail-closed market evidence admission boundary."""
from datetime import datetime, timezone

from app.services.market_research_evidence_gate import assess_market_evidence


NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)


def verified(evidence):
    return assess_market_evidence(evidence, now=NOW, trusted_verification={
        'licenseVerified': evidence.get('licenseVerified'),
        'sourceAttributionVerified': evidence.get('sourceAttributionVerified'),
        'corporateActionsStatus': evidence.get('corporateActionsStatus'),
        'coverageStatus': evidence.get('coverageStatus'),
        'independentReconciliation': evidence.get('independentReconciliation'),
    })


def valid_evidence():
    return {
        "instrumentId": "MSFT:XNAS",
        "source": "example-provider",
        "license": "explicitly-approved-research-use",
        "observationAt": "2026-11-05T21:00:00Z",
        "availableAt": "2026-11-05T21:01:00Z",
        "retrievedAt": "2026-11-05T21:02:00Z",
        "currency": "USD",
        "licenseVerified": True,
        "sourceAttributionVerified": True,
        "corporateActionsStatus": "verified",
        "coverageStatus": "verified",
        "independentReconciliation": True,
    }


def test_complete_contract_admitted_only_for_research():
    result = verified(valid_evidence())
    assert result == {"accepted": True, "reasons": [], "mode": "research_only", "orderExecutionAllowed": False}


def test_missing_license_and_provenance_rejected():
    evidence = valid_evidence()
    evidence.update(licenseVerified=False, sourceAttributionVerified=False)
    result = verified(evidence)
    assert not result["accepted"]
    assert "license_unverified" in result["reasons"]
    assert "source_unverified" in result["reasons"]


def test_future_retrieval_and_pit_inversion_rejected():
    evidence = valid_evidence()
    evidence["availableAt"] = "2026-11-07T21:01:00Z"
    result = verified(evidence)
    assert not result["accepted"]
    assert "invalid_pit_order" in result["reasons"]


def test_naive_dates_and_unverified_corporate_actions_rejected():
    evidence = valid_evidence()
    evidence["observationAt"] = "2026-11-05T21:00:00"
    evidence["corporateActionsStatus"] = "unknown"
    result = verified(evidence)
    assert "invalid_timestamps" in result["reasons"]
    assert "corporate_actions_unverified" in result["reasons"]


def test_no_inferred_reconciliation_or_coverage():
    evidence = valid_evidence()
    evidence.pop("independentReconciliation")
    evidence["coverageStatus"] = "partial"
    result = verified(evidence)
    assert "reconciliation_unverified" in result["reasons"]
    assert "coverage_unverified" in result["reasons"]


def test_stale_observation_rejected_even_if_recently_retrieved():
    evidence = valid_evidence()
    evidence["observationAt"] = "2026-10-01T21:00:00Z"
    result = verified(evidence)
    assert not result["accepted"]
    assert "stale_observation" in result["reasons"]


def test_future_observation_rejected_even_when_retrieval_is_future():
    evidence = valid_evidence()
    evidence["observationAt"] = "2026-11-07T19:00:00Z"
    evidence["availableAt"] = "2026-11-07T19:01:00Z"
    evidence["retrievedAt"] = "2026-11-07T19:02:00Z"
    result = verified(evidence)
    assert "future_market_evidence" in result["reasons"]
    assert "future_retrieval" in result["reasons"]


def test_noncanonical_currency_rejected():
    evidence = valid_evidence()
    evidence["currency"] = "usd"
    result = verified(evidence)
    assert not result["accepted"]
    assert "invalid_currency" in result["reasons"]


def test_provider_self_attestation_cannot_bypass_trusted_verification():
    result = assess_market_evidence(valid_evidence(), now=NOW)
    assert not result['accepted']
    assert 'license_unverified' in result['reasons']
    assert 'reconciliation_unverified' in result['reasons']
