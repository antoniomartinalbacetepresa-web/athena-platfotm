from __future__ import annotations

import copy

import pytest

from app.services.recommendation_calibrated_live_candidate_service import (
    RecommendationCalibratedLiveCandidateService,
)


class FakeLiveCandidateService:
    def validate_artifact(self, artifact):
        return artifact


class FakeDecisionService:
    def __init__(self, decision):
        self.decision = decision

    def load_verified(self, *, decision_id: str):
        return self.decision if decision_id == "decision-v1" else None


def _candidate() -> dict:
    return {
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": "1" * 64,
        "symbol": "AAPL",
        "asOf": "2026-09-01T12:00:00+00:00",
        "instrumentId": 101,
        "researchGateFingerprint": "a" * 64,
        "confirmationEvidenceFingerprint": "c" * 64,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "expectedExcessReturn": 0.01,
                "modelFingerprint": "7" * 64,
            },
            "30": {
                "horizonDays": 30,
                "expectedExcessReturn": 0.02,
                "modelFingerprint": "3" * 64,
            },
            "90": {
                "horizonDays": 90,
                "expectedExcessReturn": None,
                "modelFingerprint": "9" * 64,
            },
        },
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
    }


def _decision() -> dict:
    return {
        "artifactVersion": "athena-production-promotion-decision-v1",
        "decisionId": "decision-v1",
        "decisionFingerprint": "d" * 64,
        "status": "promotion_evidence_accepted_for_calibration",
        "researchGateFingerprint": "a" * 64,
        "protocolId": "prod-v1",
        "protocolFingerprint": "b" * 64,
        "confirmationEvidenceFingerprint": "c" * 64,
        "evidenceAssessmentFingerprint": "e" * 64,
        "requiredHorizons": [7, 30, 90],
        "modelFingerprintsByHorizon": {
            "7": "7" * 64,
            "30": "3" * 64,
            "90": "9" * 64,
        },
        "selectionFingerprintsByHorizon": {
            "7": "8" * 64,
            "30": "4" * 64,
            "90": "a" * 64,
        },
        "calibrationEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticProductionPromotion": False,
        "automaticTrading": False,
    }


def _service(decision=None):
    return RecommendationCalibratedLiveCandidateService(
        live_candidate_service=FakeLiveCandidateService(),
        decision_service=FakeDecisionService(decision or _decision()),
    )


def test_exact_live_models_bind_to_oos_evidence_without_enabling_advice():
    result = _service().bind(
        live_candidate=_candidate(), promotion_decision_id="decision-v1"
    )

    assert result["status"] == "live_candidate_bound_to_oos_calibration_evidence"
    assert result["calibrationReady"] is True
    assert result["horizons"]["7"]["calibrationEvidenceBound"] is True
    assert result["horizons"]["30"]["calibrationEvidenceBound"] is True
    assert result["horizons"]["90"]["reason"] == "no_live_inference"
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["automaticTrading"] is False
    assert _service().validate_artifact(result) == result


def test_research_gate_and_confirmation_identity_must_match():
    candidate = _candidate()
    candidate["researchGateFingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="otra research gate"):
        _service().bind(live_candidate=candidate, promotion_decision_id="decision-v1")

    candidate = _candidate()
    candidate["confirmationEvidenceFingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="otra evidencia de confirmación"):
        _service().bind(live_candidate=candidate, promotion_decision_id="decision-v1")


def test_each_inferred_horizon_must_use_exact_calibrated_model():
    candidate = _candidate()
    candidate["horizons"]["30"]["modelFingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="modelo aceptado"):
        _service().bind(live_candidate=candidate, promotion_decision_id="decision-v1")

    decision = _decision()
    del decision["modelFingerprintsByHorizon"]["30"]
    with pytest.raises(ValueError, match="no incluido"):
        _service(decision).bind(
            live_candidate=_candidate(), promotion_decision_id="decision-v1"
        )


def test_missing_or_productive_decision_fails_closed():
    with pytest.raises(ValueError, match="no está registrada"):
        _service().bind(live_candidate=_candidate(), promotion_decision_id="missing")

    decision = _decision()
    decision["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible=False"):
        _service(decision).bind(
            live_candidate=_candidate(), promotion_decision_id="decision-v1"
        )


def test_calibrated_artifact_tampering_is_detected():
    service = _service()
    result = service.bind(
        live_candidate=_candidate(), promotion_decision_id="decision-v1"
    )
    changed = copy.deepcopy(result)
    changed["horizons"]["7"]["modelFingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(changed)
