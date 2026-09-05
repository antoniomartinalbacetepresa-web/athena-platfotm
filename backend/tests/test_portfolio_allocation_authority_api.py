from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api import portfolio as portfolio_api


AS_OF = "2026-09-05T12:00:00+00:00"


class FakeCorrelationStore:
    calls = []

    def calculate_and_seal(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "portfolio_correlation_evidence_sealed_non_advisory",
            "evidenceFingerprint": "a" * 64,
            "recordFingerprint": "b" * 64,
            "persistedAt": "2026-09-05T12:01:00+00:00",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }


class FakeAuthorizedAllocation:
    calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "verified_allocation_pipeline_non_advisory",
            "allocationCandidate": {"status": "allocation_candidate_non_advisory"},
            "correlationAuthority": [],
            "correlationAuthorityBoundToAllocation": True,
            "callerSuppliedCorrelationArtifactsAccepted": False,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "correlationMustResolveFromAppendOnlyBackendAuthority": True,
                "callerSuppliedCorrelationJsonAccepted": False,
                "automaticTrading": False,
            },
        }


def test_correlation_evidence_api_calculates_and_seals_backend_authority(monkeypatch):
    FakeCorrelationStore.calls = []
    monkeypatch.setattr(
        portfolio_api,
        "RecommendationPortfolioCorrelationEvidenceStoreService",
        FakeCorrelationStore,
    )

    result = portfolio_api.post_portfolio_correlation_evidence(
        {
            "leftInstrumentId": 10,
            "rightInstrumentId": 20,
            "sourceProvider": "YAHOO_CHART",
            "knowledgeCutoff": AS_OF,
        }
    )

    assert result["data"]["evidenceFingerprint"] == "a" * 64
    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["productionEligible"] is False
    assert result["data"]["allocationEligible"] is False
    assert result["data"]["automaticTrading"] is False
    assert FakeCorrelationStore.calls[0]["knowledge_cutoff"] == datetime.fromisoformat(AS_OF)


def test_allocation_api_accepts_fingerprints_not_raw_authority_artifacts(monkeypatch):
    FakeAuthorizedAllocation.calls = []
    monkeypatch.setattr(
        portfolio_api,
        "RecommendationAuthorizedAllocationPipelineService",
        FakeAuthorizedAllocation,
    )
    result = portfolio_api.post_portfolio_allocation_candidate(
        {
            "uncertaintyBoundActionCandidateFingerprint": "c" * 64,
            "allocationPolicyId": "policy-001",
            "economicContract": {"economicContractFingerprint": "d" * 64},
            "referenceCapital": 10000.0,
            "baseCurrency": "EUR",
            "positions": [],
            "correlationEvidenceFingerprints": ["a" * 64],
            "asOf": AS_OF,
        }
    )

    call = FakeAuthorizedAllocation.calls[0]
    assert call["uncertainty_bound_action_candidate_fingerprint"] == "c" * 64
    assert call["correlation_evidence_fingerprints"] == ["a" * 64]
    assert "correlation_evidence" not in call
    assert result["data"]["correlationAuthorityBoundToAllocation"] is True
    assert result["data"]["callerSuppliedCorrelationArtifactsAccepted"] is False
    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["productionEligible"] is False
    assert result["data"]["allocationEligible"] is False
    assert result["data"]["automaticTrading"] is False


def test_allocation_api_rejects_raw_correlation_json_without_fingerprint_list(monkeypatch):
    monkeypatch.setattr(
        portfolio_api,
        "RecommendationAuthorizedAllocationPipelineService",
        FakeAuthorizedAllocation,
    )
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(
            {
                "uncertaintyBoundActionCandidateFingerprint": "c" * 64,
                "allocationPolicyId": "policy-001",
                "economicContract": {"economicContractFingerprint": "d" * 64},
                "referenceCapital": 10000.0,
                "baseCurrency": "EUR",
                "positions": [],
                "correlationEvidence": [{"correlation": 0.1}],
                "asOf": AS_OF,
            }
        )
    assert exc_info.value.status_code == 400
    assert "correlationEvidenceFingerprints" in exc_info.value.detail


def test_allocation_api_blocks_any_production_escape(monkeypatch):
    class UnsafeAllocation:
        def build(self, **kwargs):
            result = FakeAuthorizedAllocation().build(**kwargs)
            result["productionEligible"] = True
            return result

    monkeypatch.setattr(
        portfolio_api,
        "RecommendationAuthorizedAllocationPipelineService",
        UnsafeAllocation,
    )
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(
            {
                "uncertaintyBoundActionCandidateFingerprint": "c" * 64,
                "allocationPolicyId": "policy-001",
                "economicContract": {"economicContractFingerprint": "d" * 64},
                "referenceCapital": 10000.0,
                "baseCurrency": "EUR",
                "positions": [],
                "correlationEvidenceFingerprints": [],
                "asOf": AS_OF,
            }
        )
    assert exc_info.value.status_code == 409
    assert "productionEligible" in exc_info.value.detail


def test_allocation_api_requires_timezone_aware_as_of(monkeypatch):
    monkeypatch.setattr(
        portfolio_api,
        "RecommendationAuthorizedAllocationPipelineService",
        FakeAuthorizedAllocation,
    )
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(
            {
                "uncertaintyBoundActionCandidateFingerprint": "c" * 64,
                "allocationPolicyId": "policy-001",
                "economicContract": {"economicContractFingerprint": "d" * 64},
                "referenceCapital": 10000.0,
                "baseCurrency": "EUR",
                "positions": [],
                "correlationEvidenceFingerprints": [],
                "asOf": "2026-09-05T12:00:00",
            }
        )
    assert exc_info.value.status_code == 400
    assert "zona horaria" in exc_info.value.detail
