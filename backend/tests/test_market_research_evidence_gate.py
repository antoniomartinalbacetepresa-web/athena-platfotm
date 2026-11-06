"""Regression tests for the fail-closed market evidence admission boundary."""
from datetime import datetime, timezone

from app.services.market_research_evidence_gate import assess_market_evidence


NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)


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
    result = assess_market_evidence(valid_evidence(), now=NOW)
    assert result == {"accepted": True, "reasons": [], "mode": "research_only", "orderExecutionAllowed": False}


def test_missing_license_and_provenance_rejected():
    evidence = valid_evidence()
    evidence.update(licenseVerified=False, sourceAttributionVerified=False)
    result = assess_market_evidence(evidence, now=NOW)
    assert not result["accepted"]
    assert "license_unverified" in result["reasons"]
    assert "source_unverified" in result["reasons"]


def test_future_retrieval_and_pit_inversion_rejected():
    evidence = valid_evidence()
    evidence["availableAt"] = "2026-11-07T21:01:00Z"
    result = assess_market_evidence(evidence, now=NOW)
    assert not result["accepted"]
    assert "invalid_pit_order" in result["reasons"]


def test_naive_dates_and_unverified_corporate_actions_rejected():
    evidence = valid_evidence()
    evidence["observationAt"] = "2026-11-05T21:00:00"
    evidence["corporateActionsStatus"] = "unknown"
    result = assess_market_evidence(evidence, now=NOW)
    assert "invalid_timestamps" in result["reasons"]
    assert "corporate_actions_unverified" in result["reasons"]


def test_no_inferred_reconciliation_or_coverage():
    evidence = valid_evidence()
    evidence.pop("independentReconciliation")
    evidence["coverageStatus"] = "partial"
    result = assess_market_evidence(evidence, now=NOW)
    assert "reconciliation_unverified" in result["reasons"]
    assert "coverage_unverified" in result["reasons"]
