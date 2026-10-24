from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.services.recommendation_uncertainty_bound_action_candidate_service import (
    RecommendationUncertaintyBoundActionCandidateService,
)


CANDIDATE_FP = "1" * 64
CALIBRATED_FP = "2" * 64
DECISION_FP = "3" * 64
PORTFOLIO_FP = "4" * 64
MODEL_FP = "5" * 64
POLICY_FP = "6" * 64
OTHER_POLICY_FP = "7" * 64
UNCERTAINTY_PROTOCOL_FP = "8" * 64
SELECTION_FP = "9" * 64
CONFIRMATION_FP = "a" * 64
CONTRACT_FP = "b" * 64


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _action_candidate() -> dict:
    core = {
        "artifactVersion": "athena-validated-action-candidate-v1",
        "candidateFingerprint": CANDIDATE_FP,
        "calibratedCandidateFingerprint": CALIBRATED_FP,
        "actionPromotionDecisionId": "decision-001",
        "actionPromotionDecisionFingerprint": DECISION_FP,
        "portfolioPolicyStateFingerprint": PORTFOLIO_FP,
        "instrumentId": 42,
        "symbol": "AAPL",
        "asOf": "2026-09-01T00:00:00+00:00",
        "horizonDays": 30,
        "modelFingerprint": MODEL_FP,
        "policyState": "flat",
        "policyFingerprint": POLICY_FP,
        "expectedExcessReturn": 0.04,
        "action": "buy",
    }
    return {
        "status": "validated_action_candidate_non_advisory",
        **core,
        "validatedActionCandidateFingerprint": _fingerprint(core),
        "actionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _uncertainty() -> dict:
    states = {
        "flat": {
            "passesPrecommittedUncertaintyCriterion": True,
            "selectedPolicyFingerprint": POLICY_FP,
            "lowerConfidenceBoundIncrementalUtilityVsHold": 0.01,
        },
        "reduced_long": {
            "passesPrecommittedUncertaintyCriterion": True,
            "selectedPolicyFingerprint": OTHER_POLICY_FP,
            "lowerConfidenceBoundIncrementalUtilityVsHold": 0.01,
        },
        "full_long": {
            "passesPrecommittedUncertaintyCriterion": True,
            "selectedPolicyFingerprint": "c" * 64,
            "lowerConfidenceBoundIncrementalUtilityVsHold": 0.01,
        },
    }
    core = {
        "artifactVersion": "athena-action-uncertainty-evidence-v1",
        "protocolId": "uncertainty-001",
        "protocolFingerprint": UNCERTAINTY_PROTOCOL_FP,
        "protocolRegisteredAt": "2025-12-01T00:00:00+00:00",
        "selectionFingerprint": SELECTION_FP,
        "confirmationFingerprint": CONFIRMATION_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "selectedAt": "2026-01-01T00:00:00+00:00",
        "confirmationAsOf": "2026-08-01T00:00:00+00:00",
        "symbolScope": None,
        "requiredHorizons": [30],
        "horizons": {
            "30": {
                "horizonDays": 30,
                "passesPrecommittedUncertaintyCriteria": True,
                "sourceRowCount": 30,
                "states": states,
            }
        },
        "allRequiredPoliciesPassUncertainty": True,
    }
    return {
        "status": "action_uncertainty_evidence_ready",
        **core,
        "actionUncertaintyEvidenceFingerprint": _fingerprint(core),
        "actionUncertaintyEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _decision(*, confirmation_fingerprint=CONFIRMATION_FP) -> dict:
    return {
        "decisionId": "decision-001",
        "decisionFingerprint": DECISION_FP,
        "actionPromotionEvidenceAccepted": True,
        "selectionFingerprint": SELECTION_FP,
        "confirmationFingerprint": confirmation_fingerprint,
        "economicContractFingerprint": CONTRACT_FP,
        "modelFingerprintsByHorizon": {"30": MODEL_FP},
        "policyFingerprintsByHorizonAndState": {
            "30": {
                "flat": POLICY_FP,
                "reduced_long": OTHER_POLICY_FP,
                "full_long": "c" * 64,
            }
        },
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticTrading": False,
    }


class _DecisionRepository:
    def __init__(self, decision=None):
        self.record = {"decision": decision or _decision()}

    def get(self, *, decision_id):
        return self.record if decision_id == "decision-001" else None

    def validate_record(self, record):
        return record


def _service(*, decision=None):
    return RecommendationUncertaintyBoundActionCandidateService(
        decision_repository=_DecisionRepository(decision)
    )


def _resign_uncertainty(payload: dict) -> None:
    core_keys = (
        "artifactVersion",
        "protocolId",
        "protocolFingerprint",
        "protocolRegisteredAt",
        "selectionFingerprint",
        "confirmationFingerprint",
        "economicContractFingerprint",
        "selectedAt",
        "confirmationAsOf",
        "symbolScope",
        "requiredHorizons",
        "horizons",
        "allRequiredPoliciesPassUncertainty",
    )
    payload["actionUncertaintyEvidenceFingerprint"] = _fingerprint(
        {key: payload.get(key) for key in core_keys}
    )


def test_exact_uncertainty_binding_preserves_action_but_not_production_or_allocation():
    result = _service().build(
        validated_action_candidate=_action_candidate(),
        uncertainty_evidence=_uncertainty(),
    )

    assert result["status"] == "uncertainty_bound_action_candidate_non_advisory"
    assert result["action"] == "buy"
    assert result["uncertaintyBoundActionEvidenceReady"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_decision_and_uncertainty_must_reference_same_first_sealed_confirmation():
    with pytest.raises(ValueError, match="otra confirmación futura"):
        _service(decision=_decision(confirmation_fingerprint="d" * 64)).build(
            validated_action_candidate=_action_candidate(),
            uncertainty_evidence=_uncertainty(),
        )


def test_current_policy_must_itself_pass_uncertainty_gate():
    uncertainty = copy.deepcopy(_uncertainty())
    uncertainty["horizons"]["30"]["states"]["flat"][
        "passesPrecommittedUncertaintyCriterion"
    ] = False
    _resign_uncertainty(uncertainty)

    with pytest.raises(ValueError, match="no supera"):
        _service().build(
            validated_action_candidate=_action_candidate(),
            uncertainty_evidence=uncertainty,
        )


def test_policy_fingerprint_mismatch_fails_closed_even_with_ready_uncertainty():
    uncertainty = copy.deepcopy(_uncertainty())
    uncertainty["horizons"]["30"]["states"]["flat"][
        "selectedPolicyFingerprint"
    ] = "e" * 64
    _resign_uncertainty(uncertainty)

    with pytest.raises(ValueError, match="otra política congelada"):
        _service().build(
            validated_action_candidate=_action_candidate(),
            uncertainty_evidence=uncertainty,
        )


def test_tampered_uncertainty_payload_fails_before_binding():
    uncertainty = _uncertainty()
    uncertainty["horizons"]["30"]["states"]["flat"][
        "lowerConfidenceBoundIncrementalUtilityVsHold"
    ] = 999.0

    with pytest.raises(ValueError, match="fue modificada"):
        _service().build(
            validated_action_candidate=_action_candidate(),
            uncertainty_evidence=uncertainty,
        )
