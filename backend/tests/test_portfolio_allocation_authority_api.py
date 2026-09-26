from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api import portfolio as portfolio_api


AS_OF = "2026-09-05T12:00:00+00:00"
ACCOUNT = {"id": 1, "email": "portfolio-test@example.invalid"}


class FakeCorrelationStore:
    calls = []
    repositories = []

    def __init__(self, *, repository):
        self.repositories.append(repository)

    def calculate_and_seal(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "portfolio_correlation_evidence_sealed_non_advisory", "evidenceFingerprint": "a" * 64, "recordFingerprint": "b" * 64, "persistedAt": "2026-09-05T12:01:00+00:00", "advisoryStatus": "no_advice", "productionEligible": False, "allocationEligible": False, "automaticTrading": False}


class FakeAuthorizedAllocation:
    calls = []
    init_kwargs = []

    def __init__(self, **kwargs):
        self.init_kwargs.append(kwargs)

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "verified_allocation_pipeline_non_advisory", "allocationCandidate": {"status": "allocation_candidate_non_advisory"}, "economicContractAuthority": {"economicContractFingerprint": "d" * 64, "resolvedFromAppendOnlyBackendAuthority": True}, "economicContractAuthorityBoundToAllocation": True, "callerSuppliedEconomicContractAccepted": False, "correlationAuthority": [], "correlationAuthorityBoundToAllocation": True, "callerSuppliedCorrelationArtifactsAccepted": False, "advisoryStatus": "no_advice", "recommendationCandidateReady": False, "productionEligible": False, "allocationEligible": False, "automaticTrading": False, "policy": {"economicContractMustResolveFromAppendOnlyBackendAuthority": True, "callerSuppliedEconomicContractAccepted": False, "correlationMustResolveFromAppendOnlyBackendAuthority": True, "callerSuppliedCorrelationJsonAccepted": False, "automaticTrading": False}}


def _allocation_payload(**overrides):
    payload = {"uncertaintyBoundActionCandidateFingerprint": "c" * 64, "allocationPolicyId": "policy-001", "referenceCapital": 10000.0, "baseCurrency": "EUR", "positions": [], "correlationEvidenceFingerprints": [], "asOf": AS_OF}
    payload.update(overrides)
    return payload


def test_correlation_evidence_api_calculates_and_seals_backend_authority(monkeypatch):
    FakeCorrelationStore.calls = []
    FakeCorrelationStore.repositories = []
    monkeypatch.setattr(portfolio_api, "RecommendationPortfolioCorrelationEvidenceStoreService", FakeCorrelationStore)
    result = portfolio_api.post_portfolio_correlation_evidence(account=ACCOUNT, payload={"leftInstrumentId": 10, "rightInstrumentId": 20, "sourceProvider": "YAHOO_CHART", "knowledgeCutoff": AS_OF})
    assert result["data"]["evidenceFingerprint"] == "a" * 64
    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["productionEligible"] is False
    assert result["data"]["allocationEligible"] is False
    assert result["data"]["automaticTrading"] is False
    assert FakeCorrelationStore.calls[0]["knowledge_cutoff"] == datetime.fromisoformat(AS_OF)
    repository = FakeCorrelationStore.repositories[0]
    assert repository._owner_user_id == ACCOUNT["id"]


def test_allocation_api_accepts_only_sealed_fingerprints_not_raw_authority_artifacts(monkeypatch):
    FakeAuthorizedAllocation.calls = []
    FakeAuthorizedAllocation.init_kwargs = []
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", FakeAuthorizedAllocation)
    result = portfolio_api.post_portfolio_allocation_candidate(account=ACCOUNT, payload=_allocation_payload(correlationEvidenceFingerprints=["a" * 64]))
    call = FakeAuthorizedAllocation.calls[0]
    init_kwargs = FakeAuthorizedAllocation.init_kwargs[0]
    assert call["uncertainty_bound_action_candidate_fingerprint"] == "c" * 64
    assert call["correlation_evidence_fingerprints"] == ["a" * 64]
    assert "economic_contract" not in call
    assert "correlation_evidence" not in call
    assert init_kwargs["correlation_repository"]._owner_user_id == ACCOUNT["id"]
    assert init_kwargs["verified_pipeline"]._valuation_repository._owner_user_id == ACCOUNT["id"]
    assert result["data"]["economicContractAuthorityBoundToAllocation"] is True
    assert result["data"]["callerSuppliedEconomicContractAccepted"] is False
    assert result["data"]["correlationAuthorityBoundToAllocation"] is True
    assert result["data"]["callerSuppliedCorrelationArtifactsAccepted"] is False
    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["productionEligible"] is False
    assert result["data"]["allocationEligible"] is False
    assert result["data"]["automaticTrading"] is False


def test_allocation_api_scopes_injected_evidence_repositories_to_authenticated_owner(monkeypatch):
    FakeAuthorizedAllocation.calls = []
    FakeAuthorizedAllocation.init_kwargs = []
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", FakeAuthorizedAllocation)
    other_account = {"id": 77, "email": "other@example.invalid"}
    portfolio_api.post_portfolio_allocation_candidate(account=other_account, payload=_allocation_payload())
    init_kwargs = FakeAuthorizedAllocation.init_kwargs[0]
    assert init_kwargs["correlation_repository"]._owner_user_id == 77
    assert init_kwargs["verified_pipeline"]._valuation_repository._owner_user_id == 77
    assert init_kwargs["correlation_repository"]._owner_user_id != ACCOUNT["id"]


def test_allocation_api_rejects_caller_supplied_economic_contract(monkeypatch):
    FakeAuthorizedAllocation.calls = []
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", FakeAuthorizedAllocation)
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(account=ACCOUNT, payload=_allocation_payload(economicContract={"economicContractFingerprint": "d" * 64}))
    assert exc_info.value.status_code == 400
    assert "economicContract no se acepta" in exc_info.value.detail
    assert FakeAuthorizedAllocation.calls == []


def test_allocation_api_rejects_raw_correlation_json_without_fingerprint_list(monkeypatch):
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", FakeAuthorizedAllocation)
    payload = _allocation_payload(correlationEvidence=[{"correlation": 0.1}])
    payload.pop("correlationEvidenceFingerprints")
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(account=ACCOUNT, payload=payload)
    assert exc_info.value.status_code == 400
    assert "correlationEvidenceFingerprints" in exc_info.value.detail


def test_allocation_api_blocks_any_production_escape(monkeypatch):
    class UnsafeAllocation:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def build(self, **kwargs):
            result = FakeAuthorizedAllocation().build(**kwargs)
            result["productionEligible"] = True
            return result
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", UnsafeAllocation)
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(account=ACCOUNT, payload=_allocation_payload())
    assert exc_info.value.status_code == 409
    assert "productionEligible" in exc_info.value.detail


def test_allocation_api_requires_timezone_aware_as_of(monkeypatch):
    monkeypatch.setattr(portfolio_api, "RecommendationAuthorizedAllocationPipelineService", FakeAuthorizedAllocation)
    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.post_portfolio_allocation_candidate(account=ACCOUNT, payload=_allocation_payload(asOf="2026-09-05T12:00:00"))
    assert exc_info.value.status_code == 400
    assert "zona horaria" in exc_info.value.detail
