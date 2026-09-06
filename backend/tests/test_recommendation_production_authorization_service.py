from __future__ import annotations

import hashlib
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_authorization_repository import (
    RecommendationProductionAuthorizationRepository,
)
from app.services.recommendation_production_authorization_service import (
    RecommendationProductionAuthorizationService,
)


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact_fp(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _FakeProductionDecisionService:
    def __init__(self, decision: dict) -> None:
        self.decision = decision

    def load_verified(self, *, decision_id: str) -> dict | None:
        return self.decision if decision_id == self.decision["decisionId"] else None


class _FakeActionDecisionRepository:
    def __init__(self, decision: dict) -> None:
        self.record = {"decision": decision}

    def get(self, *, decision_id: str) -> dict | None:
        return self.record if decision_id == self.record["decision"]["decisionId"] else None

    def validate_record(self, record: dict) -> dict:
        return record


class _FakeAuthorizationRepository:
    ARTIFACT_VERSION = "athena-production-recommendation-authorization-v1"

    def __init__(self) -> None:
        self.draft: dict | None = None

    def register(self, *, authorization_draft: dict) -> dict:
        self.draft = authorization_draft
        return {"authorization": authorization_draft}


class _FakeCalibratedCandidateService:
    def validate_artifact(self, artifact: dict) -> dict:
        return artifact


def _chain() -> tuple[dict, dict, dict, dict, dict]:
    model = _fp("model-30")
    candidate = _fp("candidate")
    calibrated_fp = _fp("calibrated")
    production_decision_fp = _fp("production-decision")
    action_decision_fp = _fp("action-decision")
    policy_fp = _fp("policy")
    portfolio_state_fp = _fp("portfolio-state")
    uncertainty_evidence_fp = _fp("uncertainty-evidence")
    economic_contract_fp = _fp("economic-contract")

    production_decision = {
        "decisionId": "prod-decision-1",
        "decisionFingerprint": production_decision_fp,
        "calibrationEvidenceReady": True,
        "modelFingerprintsByHorizon": {"30": model},
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticTrading": False,
    }
    calibrated = {
        "artifactVersion": "athena-calibrated-live-candidate-v1",
        "candidateFingerprint": candidate,
        "calibratedCandidateFingerprint": calibrated_fp,
        "promotionDecisionId": "prod-decision-1",
        "promotionDecisionFingerprint": production_decision_fp,
        "instrumentId": "ins-aapl-xnas-usd",
        "symbol": "AAPL",
        "asOf": "2026-09-06T16:00:00+00:00",
        "horizons": {
            "30": {
                "horizonDays": 30,
                "calibrationEvidenceBound": True,
                "modelFingerprint": model,
            }
        },
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticTrading": False,
    }
    action_decision = {
        "decisionId": "action-decision-1",
        "decisionFingerprint": action_decision_fp,
        "actionPromotionEvidenceAccepted": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticTrading": False,
    }
    action_core = {
        "artifactVersion": "athena-validated-action-candidate-v1",
        "candidateFingerprint": candidate,
        "calibratedCandidateFingerprint": calibrated_fp,
        "actionPromotionDecisionId": "action-decision-1",
        "actionPromotionDecisionFingerprint": action_decision_fp,
        "portfolioPolicyStateFingerprint": portfolio_state_fp,
        "instrumentId": "ins-aapl-xnas-usd",
        "symbol": "AAPL",
        "asOf": "2026-09-06T16:00:00+00:00",
        "horizonDays": 30,
        "modelFingerprint": model,
        "policyState": "flat",
        "policyFingerprint": policy_fp,
        "expectedExcessReturn": 0.04,
        "action": "buy",
    }
    action = {
        "status": "validated_action_candidate_non_advisory",
        **action_core,
        "validatedActionCandidateFingerprint": _artifact_fp(action_core),
        "actionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }
    uncertainty_core = {
        "artifactVersion": "athena-uncertainty-bound-action-candidate-v1",
        "validatedActionCandidateFingerprint": action[
            "validatedActionCandidateFingerprint"
        ],
        "actionUncertaintyEvidenceFingerprint": uncertainty_evidence_fp,
        "actionPromotionDecisionId": "action-decision-1",
        "actionPromotionDecisionFingerprint": action_decision_fp,
        "economicContractFingerprint": economic_contract_fp,
        "candidateFingerprint": candidate,
        "instrumentId": "ins-aapl-xnas-usd",
        "symbol": "AAPL",
        "asOf": "2026-09-06T16:00:00+00:00",
        "horizonDays": 30,
        "modelFingerprint": model,
        "policyState": "flat",
        "policyFingerprint": policy_fp,
        "portfolioPolicyStateFingerprint": portfolio_state_fp,
        "action": "buy",
    }
    uncertainty_bound = {
        "status": "uncertainty_bound_action_candidate_non_advisory",
        **uncertainty_core,
        "uncertaintyBoundActionCandidateFingerprint": _artifact_fp(uncertainty_core),
        "actionEvidenceReady": True,
        "actionUncertaintyEvidenceReady": True,
        "uncertaintyBoundActionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }
    return production_decision, calibrated, action_decision, action, uncertainty_bound


def _service() -> tuple[RecommendationProductionAuthorizationService, _FakeAuthorizationRepository]:
    production_decision, _, action_decision, _, _ = _chain()
    authorization_repository = _FakeAuthorizationRepository()
    return (
        RecommendationProductionAuthorizationService(
            production_decision_service=_FakeProductionDecisionService(
                production_decision
            ),
            action_decision_repository=_FakeActionDecisionRepository(action_decision),
            authorization_repository=authorization_repository,
            calibrated_candidate_service=_FakeCalibratedCandidateService(),
        ),
        authorization_repository,
    )


def test_authorization_requires_exact_chain_and_stays_non_operational_for_allocation() -> None:
    _, calibrated, _, action, uncertainty_bound = _chain()
    service, repository = _service()

    record = service.authorize(
        authorization_id="auth-1",
        production_promotion_decision_id="prod-decision-1",
        calibrated_candidate=calibrated,
        validated_action_candidate=action,
        uncertainty_bound_action_candidate=uncertainty_bound,
        operator_id="local-governance-operator",
        authorization_reason="Revisión humana de toda la cadena OOS sellada.",
        human_review_confirmed=True,
    )

    authorization = record["authorization"]
    assert authorization["status"] == "production_recommendation_authorized"
    assert authorization["productionEligible"] is True
    assert authorization["recommendationCandidateReady"] is True
    assert authorization["allocationEligible"] is False
    assert authorization["automaticProductionPromotion"] is False
    assert authorization["automaticTrading"] is False
    assert authorization["authorizationMethod"] == "offline_local_operator"
    assert repository.draft is authorization


def test_authorization_fails_closed_without_human_review() -> None:
    _, calibrated, _, action, uncertainty_bound = _chain()
    service, _ = _service()

    with pytest.raises(ValueError, match="revisión humana"):
        service.authorize(
            authorization_id="auth-1",
            production_promotion_decision_id="prod-decision-1",
            calibrated_candidate=calibrated,
            validated_action_candidate=action,
            uncertainty_bound_action_candidate=uncertainty_bound,
            operator_id="local-governance-operator",
            authorization_reason="Revisión humana de toda la cadena OOS sellada.",
            human_review_confirmed=False,
        )


def test_authorization_rejects_tampered_uncertainty_action() -> None:
    _, calibrated, _, action, uncertainty_bound = _chain()
    service, _ = _service()
    tampered = dict(uncertainty_bound)
    tampered["action"] = "sell"

    with pytest.raises(ValueError, match="modificada"):
        service.authorize(
            authorization_id="auth-1",
            production_promotion_decision_id="prod-decision-1",
            calibrated_candidate=calibrated,
            validated_action_candidate=action,
            uncertainty_bound_action_candidate=tampered,
            operator_id="local-governance-operator",
            authorization_reason="Revisión humana de toda la cadena OOS sellada.",
            human_review_confirmed=True,
        )


def test_authorization_repository_is_append_only_and_detects_tampering(tmp_path) -> None:
    repository = RecommendationProductionAuthorizationRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )
    draft = {
        "artifactVersion": repository.ARTIFACT_VERSION,
        "authorizationId": "auth-persisted-1",
        "status": "production_recommendation_authorized",
        "productionPromotionDecisionId": "prod-1",
        "productionPromotionDecisionFingerprint": _fp("prod"),
        "calibratedCandidateFingerprint": _fp("calibrated"),
        "validatedActionCandidateFingerprint": _fp("action"),
        "uncertaintyBoundActionCandidateFingerprint": _fp("uncertainty"),
        "actionPromotionDecisionId": "action-1",
        "actionPromotionDecisionFingerprint": _fp("action-decision"),
        "candidateFingerprint": _fp("candidate"),
        "instrumentId": "ins-aapl-xnas-usd",
        "symbol": "AAPL",
        "asOf": "2026-09-06T16:00:00+00:00",
        "horizonDays": 30,
        "modelFingerprint": _fp("model"),
        "policyState": "flat",
        "policyFingerprint": _fp("policy"),
        "action": "buy",
        "operatorId": "local-governance-operator",
        "authorizationReason": "Revisión humana completa de la evidencia productiva.",
        "humanReviewConfirmed": True,
        "authorizationMethod": "offline_local_operator",
        "advisoryStatus": "production_recommendation",
        "recommendationCandidateReady": True,
        "productionEligible": True,
        "allocationEligible": False,
        "automaticProductionPromotion": False,
        "automaticTrading": False,
    }

    record = repository.register(authorization_draft=draft)
    loaded = repository.get(authorization_id="auth-persisted-1")
    assert loaded is not None
    assert loaded["authorization"] == record["authorization"]
    assert loaded["authorization"]["automaticTrading"] is False

    with repository._database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_production_authorizations
            SET operator_id = 'tampered-operator'
            WHERE authorization_id = 'auth-persisted-1'
            """
        )

    with pytest.raises(ValueError, match="operatorId"):
        repository.get(authorization_id="auth-persisted-1")
