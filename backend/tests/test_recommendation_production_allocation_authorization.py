from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_allocation_authorization_repository import (
    RecommendationProductionAllocationAuthorizationRepository,
)
from app.services.recommendation_production_allocation_authorization_service import (
    RecommendationProductionAllocationAuthorizationService,
)


AS_OF = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
ACTION_FP = "a" * 64
RECOMMENDATION_FP = "b" * 64
CONTRACT_FP = "c" * 64
ALLOCATION_FP = "d" * 64
PIPELINE_FP = "e" * 64
VALUATION_FP = "f" * 64
POLICY_FP = "1" * 64
CORRELATION_FP = "2" * 64


class FakeRecommendationAuthorizationRepository:
    def __init__(self, authorization: dict[str, object]) -> None:
        self.record = {
            "authorization_id": authorization["authorizationId"],
            "authorization_fingerprint": authorization["authorizationFingerprint"],
            "authorization": authorization,
        }

    def get(self, *, authorization_id: str):
        return self.record if authorization_id == self.record["authorization_id"] else None

    def validate_record(self, record):
        return record


class FakeAuthorizedAllocationPipeline:
    def __init__(self, artifact: dict[str, object]) -> None:
        self.artifact = artifact
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.artifact)


class CapturingAllocationAuthorizationRepository:
    def __init__(self) -> None:
        self.draft: dict[str, object] | None = None

    def register(self, *, authorization_draft):
        self.draft = copy.deepcopy(authorization_draft)
        return {"authorization": copy.deepcopy(authorization_draft)}


def _recommendation() -> dict[str, object]:
    return {
        "authorizationId": "prod-rec-1",
        "authorizationFingerprint": RECOMMENDATION_FP,
        "status": "production_recommendation_authorized",
        "uncertaintyBoundActionCandidateFingerprint": ACTION_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "instrumentId": 101,
        "symbol": "TEST",
        "asOf": AS_OF.isoformat(),
        "action": "buy",
        "policyState": "flat",
        "humanReviewConfirmed": True,
        "advisoryStatus": "production_recommendation",
        "recommendationCandidateReady": True,
        "productionEligible": True,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _allocation() -> dict[str, object]:
    return {
        "status": "allocation_candidate_non_advisory",
        "uncertaintyBoundActionCandidateFingerprint": ACTION_FP,
        "allocationPolicyId": "policy-1",
        "allocationPolicyFingerprint": POLICY_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "portfolioValuationEvidenceFingerprint": VALUATION_FP,
        "instrumentId": 101,
        "symbol": "TEST",
        "asOf": AS_OF.isoformat(),
        "baseCurrency": "EUR",
        "action": "buy",
        "policyState": "flat",
        "referenceCapital": 100000.0,
        "targetAmountInBaseCurrency": 5000.0,
        "deltaAmountInBaseCurrency": 5000.0,
        "allocationCandidateFingerprint": ALLOCATION_FP,
        "allocationEvidenceStructurallyReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _pipeline() -> dict[str, object]:
    return {
        "status": "verified_allocation_pipeline_non_advisory",
        "asOf": AS_OF.isoformat(),
        "uncertaintyBoundActionCandidateFingerprint": ACTION_FP,
        "portfolioValuationEvidenceFingerprint": VALUATION_FP,
        "verifiedAllocationPipelineFingerprint": PIPELINE_FP,
        "allocationCandidate": _allocation(),
        "economicContractAuthorityBoundToAllocation": True,
        "callerSuppliedEconomicContractAccepted": False,
        "correlationAuthority": [
            {"evidenceFingerprint": CORRELATION_FP}
        ],
        "correlationAuthorityBoundToAllocation": True,
        "callerSuppliedCorrelationArtifactsAccepted": False,
        "portfolioValuationSealedBeforeAllocation": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _service(*, recommendation=None, pipeline=None):
    sink = CapturingAllocationAuthorizationRepository()
    source = FakeAuthorizedAllocationPipeline(pipeline or _pipeline())
    service = RecommendationProductionAllocationAuthorizationService(
        recommendation_authorization_repository=FakeRecommendationAuthorizationRepository(
            recommendation or _recommendation()
        ),
        authorized_allocation_pipeline=source,
        allocation_authorization_repository=sink,
    )
    return service, source, sink


def _authorize(service):
    return service.authorize(
        recommendation_authorization_id="prod-rec-1",
        allocation_authorization_id="prod-allocation-1",
        allocation_policy_id="policy-1",
        reference_capital=100000.0,
        base_currency="EUR",
        positions=[],
        correlation_evidence_fingerprints=[CORRELATION_FP],
        as_of=AS_OF,
        operator_id="risk-committee",
        authorization_reason="Revisión humana de allocation con evidencia PIT sellada.",
        human_review_confirmed=True,
    )


def test_authorization_binds_productive_recommendation_to_exact_allocation():
    service, source, sink = _service()

    result = _authorize(service)

    assert source.calls[0]["uncertainty_bound_action_candidate_fingerprint"] == ACTION_FP
    assert sink.draft is not None
    assert sink.draft["recommendationAuthorizationFingerprint"] == RECOMMENDATION_FP
    assert sink.draft["allocationCandidateFingerprint"] == ALLOCATION_FP
    assert sink.draft["portfolioValuationEvidenceFingerprint"] == VALUATION_FP
    assert sink.draft["economicContractFingerprint"] == CONTRACT_FP
    assert sink.draft["productionEligible"] is True
    assert sink.draft["allocationEligible"] is True
    assert sink.draft["executionEligible"] is False
    assert sink.draft["orderRoutingEligible"] is False
    assert sink.draft["automaticTrading"] is False
    assert result["authorization"]["allocationEligible"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("uncertaintyBoundActionCandidateFingerprint", "9" * 64, "acción productiva"),
        ("instrumentId", 202, "instrumentId"),
        ("symbol", "OTHER", "symbol"),
        ("action", "hold", "acción productiva"),
        ("policyState", "full_long", "estado de cartera"),
        ("economicContractFingerprint", "8" * 64, "contrato económico"),
        ("baseCurrency", "USD", "moneda base"),
        ("referenceCapital", 99999.0, "capital de referencia"),
    ],
)
def test_authorization_rejects_recomposed_allocation(field, value, message):
    pipeline = _pipeline()
    allocation = pipeline["allocationCandidate"]
    assert isinstance(allocation, dict)
    allocation[field] = value
    service, _, sink = _service(pipeline=pipeline)

    with pytest.raises(ValueError, match=message):
        _authorize(service)

    assert sink.draft is None


def test_authorization_rejects_different_pit_cutoff_and_missing_human_review():
    pipeline = _pipeline()
    allocation = pipeline["allocationCandidate"]
    assert isinstance(allocation, dict)
    allocation["asOf"] = datetime(2026, 8, 20, 15, 1, tzinfo=timezone.utc).isoformat()
    service, _, sink = _service(pipeline=pipeline)
    with pytest.raises(ValueError, match="corte PIT"):
        _authorize(service)
    assert sink.draft is None

    service, _, sink = _service()
    with pytest.raises(ValueError, match="revisión humana"):
        service.authorize(
            recommendation_authorization_id="prod-rec-1",
            allocation_authorization_id="prod-allocation-1",
            allocation_policy_id="policy-1",
            reference_capital=100000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence_fingerprints=[CORRELATION_FP],
            as_of=AS_OF,
            operator_id="risk-committee",
            authorization_reason="Revisión humana de allocation con evidencia PIT sellada.",
            human_review_confirmed=False,
        )
    assert sink.draft is None


def _repository_draft() -> dict[str, object]:
    return {
        "artifactVersion": "athena-production-allocation-authorization-v1",
        "authorizationId": "prod-allocation-1",
        "status": "production_allocation_authorized",
        "recommendationAuthorizationId": "prod-rec-1",
        "recommendationAuthorizationFingerprint": RECOMMENDATION_FP,
        "uncertaintyBoundActionCandidateFingerprint": ACTION_FP,
        "allocationCandidateFingerprint": ALLOCATION_FP,
        "verifiedAllocationPipelineFingerprint": PIPELINE_FP,
        "portfolioValuationEvidenceFingerprint": VALUATION_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "allocationPolicyId": "policy-1",
        "allocationPolicyFingerprint": POLICY_FP,
        "instrumentId": 101,
        "symbol": "TEST",
        "asOf": AS_OF.isoformat(),
        "baseCurrency": "EUR",
        "action": "buy",
        "policyState": "flat",
        "referenceCapital": 100000.0,
        "targetAmountInBaseCurrency": 5000.0,
        "deltaAmountInBaseCurrency": 5000.0,
        "correlationEvidenceFingerprints": [CORRELATION_FP],
        "allocationCandidate": _allocation(),
        "operatorId": "risk-committee",
        "authorizationReason": "Revisión humana de allocation con evidencia PIT sellada.",
        "humanReviewConfirmed": True,
        "authorizationMethod": "offline_local_operator",
        "advisoryStatus": "production_allocation",
        "productionEligible": True,
        "allocationEligible": True,
        "automaticAllocationPromotion": False,
        "executionEligible": False,
        "orderRoutingEligible": False,
        "automaticTrading": False,
    }


def test_repository_is_append_only_strict_json_and_detects_tampering(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.sqlite3")
    repository = RecommendationProductionAllocationAuthorizationRepository(database)
    record = repository.register(authorization_draft=_repository_draft())

    assert record["authorization"]["allocationEligible"] is True
    assert record["authorization"]["automaticTrading"] is False

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_production_allocation_authorizations
            SET operator_id = ? WHERE authorization_id = ?
            """,
            ("attacker", "prod-allocation-1"),
        )
    with pytest.raises(ValueError, match="operatorId"):
        repository.get(authorization_id="prod-allocation-1")

    database2 = AthenaDatabase(tmp_path / "finite.sqlite3")
    repository2 = RecommendationProductionAllocationAuthorizationRepository(database2)
    draft = _repository_draft()
    allocation = draft["allocationCandidate"]
    assert isinstance(allocation, dict)
    allocation["nestedNonFinite"] = float("nan")
    with pytest.raises(ValueError, match="no serializables o no finitos"):
        repository2.register(authorization_draft=draft)
    with database2.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM athena_recommendation_production_allocation_authorizations"
        ).fetchone()[0]
    assert count == 0
