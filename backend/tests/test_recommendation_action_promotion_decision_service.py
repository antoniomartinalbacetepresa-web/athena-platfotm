from __future__ import annotations

from copy import deepcopy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_action_promotion_decision_repository import (
    RecommendationActionPromotionDecisionRepository,
)
from app.services.recommendation_action_promotion_decision_service import (
    RecommendationActionPromotionDecisionService,
)


class _EvidenceService:
    def __init__(self, *, ready=True):
        self.ready = ready

    def evaluate_registered(
        self,
        *,
        confirmation_artifact,
        protocol_id,
        model_identity_attestation,
    ):
        return {
            "status": (
                "model_bound_action_promotion_evidence_ready"
                if self.ready
                else "model_bound_action_promotion_evidence_insufficient"
            ),
            "modelBoundActionPromotionEvidenceFingerprint": "1" * 64,
            "actionPromotionEvidenceFingerprint": "2" * 64,
            "modelIdentityAttestationFingerprint": "3" * 64,
            "protocolId": protocol_id,
            "protocolFingerprint": "4" * 64,
            "selectionFingerprint": "5" * 64,
            "confirmationFingerprint": "6" * 64,
            "economicContractFingerprint": "7" * 64,
            "requiredHorizons": [30],
            "modelFingerprintsByHorizon": {"30": "8" * 64},
            "policyFingerprintsByHorizonAndState": {
                "30": {
                    "flat": "a" * 64,
                    "reduced_long": "b" * 64,
                    "full_long": "c" * 64,
                }
            },
            "modelBoundActionPromotionEvidenceReady": self.ready,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "allocation": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }


def _repository(tmp_path):
    return RecommendationActionPromotionDecisionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )


def test_ready_model_bound_evidence_is_persisted_without_enabling_advice(tmp_path):
    repository = _repository(tmp_path)
    service = RecommendationActionPromotionDecisionService(
        evidence_service=_EvidenceService(ready=True),
        repository=repository,
    )

    result = service.decide_registered(
        decision_id="action-decision-001",
        confirmation_artifact={},
        protocol_id="action-protocol-001",
        model_identity_attestation={},
    )

    assert result["status"] == "action_promotion_decision_persisted"
    assert result["actionPromotionEvidenceAccepted"] is True
    assert result["modelFingerprintsByHorizon"] == {"30": "8" * 64}
    assert result["policyFingerprintsByHorizonAndState"]["30"]["flat"] == "a" * 64
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["allocation"] is None
    assert result["automaticTrading"] is False

    persisted = repository.get(decision_id="action-decision-001")
    assert persisted is not None
    assert persisted["decision"]["decisionFingerprint"] == result["decisionFingerprint"]


def test_insufficient_model_bound_evidence_cannot_be_persisted(tmp_path):
    service = RecommendationActionPromotionDecisionService(
        evidence_service=_EvidenceService(ready=False),
        repository=_repository(tmp_path),
    )

    with pytest.raises(ValueError, match="no supera"):
        service.decide_registered(
            decision_id="action-decision-001",
            confirmation_artifact={},
            protocol_id="action-protocol-001",
            model_identity_attestation={},
        )


def test_same_evidence_cannot_receive_a_second_decision_id(tmp_path):
    repository = _repository(tmp_path)
    service = RecommendationActionPromotionDecisionService(
        evidence_service=_EvidenceService(ready=True),
        repository=repository,
    )
    service.decide_registered(
        decision_id="action-decision-001",
        confirmation_artifact={},
        protocol_id="action-protocol-001",
        model_identity_attestation={},
    )

    with pytest.raises(ValueError, match="misma evidencia"):
        service.decide_registered(
            decision_id="action-decision-002",
            confirmation_artifact={},
            protocol_id="action-protocol-001",
            model_identity_attestation={},
        )


def test_decision_record_detects_database_tampering(tmp_path):
    repository = _repository(tmp_path)
    service = RecommendationActionPromotionDecisionService(
        evidence_service=_EvidenceService(ready=True),
        repository=repository,
    )
    service.decide_registered(
        decision_id="action-decision-001",
        confirmation_artifact={},
        protocol_id="action-protocol-001",
        model_identity_attestation={},
    )

    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT decision_json FROM athena_recommendation_action_promotion_decisions WHERE decision_id = ?",
            ("action-decision-001",),
        ).fetchone()
        assert row is not None
        import json

        payload = json.loads(row["decision_json"])
        payload["policyFingerprintsByHorizonAndState"]["30"]["flat"] = "f" * 64
        connection.execute(
            "UPDATE athena_recommendation_action_promotion_decisions SET decision_json = ? WHERE decision_id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), "action-decision-001"),
        )

    with pytest.raises(ValueError, match="modificada"):
        repository.get(decision_id="action-decision-001")


def test_repository_rejects_production_escape_in_evidence(tmp_path):
    evidence = _EvidenceService(ready=True).evaluate_registered(
        confirmation_artifact={},
        protocol_id="action-protocol-001",
        model_identity_attestation={},
    )
    escaped = deepcopy(evidence)
    escaped["productionEligible"] = True

    with pytest.raises(ValueError, match="productionEligible"):
        _repository(tmp_path).append(
            decision_id="action-decision-001",
            evidence=escaped,
        )
