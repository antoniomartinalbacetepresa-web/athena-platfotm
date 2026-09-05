from __future__ import annotations

import hashlib
import json

import pytest

from app.services.recommendation_action_model_identity_attestation_service import (
    RecommendationActionModelIdentityAttestationService,
)
from app.services.recommendation_model_bound_action_promotion_evidence_service import (
    RecommendationModelBoundActionPromotionEvidenceService,
)


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


class _PanelValidator:
    def validate_artifact(self, artifact):
        return artifact


class _CandidateValidator:
    def validate_artifact(self, artifact):
        return artifact


class _CandidateRepository:
    def __init__(self, models=None):
        models = models or {1: "1" * 64, 2: "1" * 64}
        self.rows = {
            candidate_id: {
                "candidate_fingerprint": ("a" if candidate_id == 1 else "b") * 64,
                "artifact": {
                    "candidateFingerprint": ("a" if candidate_id == 1 else "b") * 64,
                    "symbol": "TEST",
                    "asOf": (
                        "2026-01-01T00:00:00+00:00"
                        if candidate_id == 1
                        else "2026-02-01T00:00:00+00:00"
                    ),
                    "horizons": {
                        "30": {
                            "horizonDays": 30,
                            "expectedExcessReturn": 0.05,
                            "modelFingerprint": models[candidate_id],
                        }
                    },
                },
            }
            for candidate_id in models
        }

    def get(self, candidate_id):
        return self.rows.get(candidate_id)


def _utility_rows(candidate_id, partition, as_of):
    return [
        {
            "partition": partition,
            "candidateId": candidate_id,
            "symbol": "TEST",
            "horizonDays": 30,
            "candidateAsOf": as_of,
            "expectedExcessReturn": 0.05,
            "currentState": state,
        }
        for state in ("flat", "reduced_long", "full_long")
    ]


def _panel():
    return {
        "utilityPanelFingerprint": "d" * 64,
        "economicContractFingerprint": "e" * 64,
        "requestedHorizons": [30],
        "trainUtilityRows": _utility_rows(1, "train", "2026-01-01T00:00:00+00:00"),
        "validationUtilityRows": _utility_rows(
            2, "validation", "2026-02-01T00:00:00+00:00"
        ),
    }


def _selection():
    core = {
        "artifactVersion": "shadow-action-threshold-selection-v1",
        "sourceUtilityPanelFingerprint": "d" * 64,
        "candidateSetFingerprint": "f" * 64,
        "economicContractFingerprint": "e" * 64,
        "requestedHorizons": [30],
        "minimumValidationRowsPerState": 10,
        "allRequestedHorizonsAndStatesSelected": True,
        "selections": {"30": {"horizonDays": 30, "allStatesSelected": True}},
    }
    return {
        "status": "shadow_action_threshold_selection_frozen_for_future_confirmation",
        **core,
        "selectionFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "futureReserveConfirmationEligible": True,
    }


def _service(models=None):
    return RecommendationActionModelIdentityAttestationService(
        candidate_repository=_CandidateRepository(models),
        candidate_validator=_CandidateValidator(),
        panel_validator=_PanelValidator(),
    )


def test_action_calibration_attests_one_exact_model_revision_per_horizon():
    result = _service().attest(utility_panel=_panel(), selection=_selection())

    assert result["status"] == "action_calibration_model_identity_attested"
    assert result["modelFingerprintsByHorizon"] == {"30": "1" * 64}
    assert result["uniqueCandidateHorizonCount"] == 2
    assert result["singleModelRevisionPerHorizon"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["automaticTrading"] is False


def test_action_calibration_fails_closed_when_model_revisions_are_mixed():
    service = _service({1: "1" * 64, 2: "2" * 64})

    with pytest.raises(ValueError, match="mezcla revisiones"):
        service.attest(utility_panel=_panel(), selection=_selection())


def test_action_calibration_fails_closed_if_signal_differs_from_persisted_candidate():
    panel = _panel()
    panel["validationUtilityRows"][0]["expectedExcessReturn"] = 0.99

    with pytest.raises(ValueError, match="señal de calibración"):
        _service().attest(utility_panel=panel, selection=_selection())


class _EvidenceService:
    def __init__(self, ready=True):
        self.ready = ready

    def evaluate_registered(self, *, confirmation_artifact, protocol_id):
        return {
            "actionPromotionEvidenceFingerprint": "3" * 64,
            "protocolId": protocol_id,
            "protocolFingerprint": "4" * 64,
            "selectionFingerprint": "5" * 64,
            "confirmationFingerprint": "6" * 64,
            "requiredHorizons": [30],
            "actionPromotionEvidenceReady": self.ready,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "automaticTrading": False,
        }


class _IdentityService:
    def __init__(self, contract="7" * 64):
        self.artifact = {
            "selectionFingerprint": "5" * 64,
            "requestedHorizons": [30],
            "economicContractFingerprint": contract,
            "modelFingerprintsByHorizon": {"30": "8" * 64},
            "modelIdentityAttestationFingerprint": "9" * 64,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "automaticTrading": False,
        }

    def validate_artifact(self, artifact):
        return artifact


def test_model_bound_action_evidence_still_does_not_enable_advice_or_trading():
    identity = _IdentityService()
    service = RecommendationModelBoundActionPromotionEvidenceService(
        evidence_service=_EvidenceService(ready=True),
        identity_service=identity,
    )
    confirmation = {"economicContractFingerprint": "7" * 64}

    result = service.evaluate_registered(
        confirmation_artifact=confirmation,
        protocol_id="action-protocol-001",
        model_identity_attestation=identity.artifact,
    )

    assert result["modelBoundActionPromotionEvidenceReady"] is True
    assert result["modelFingerprintsByHorizon"] == {"30": "8" * 64}
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["allocation"] is None
    assert result["automaticTrading"] is False


def test_model_bound_action_evidence_rejects_wrong_economic_contract():
    identity = _IdentityService(contract="a" * 64)
    service = RecommendationModelBoundActionPromotionEvidenceService(
        evidence_service=_EvidenceService(ready=True),
        identity_service=identity,
    )

    with pytest.raises(ValueError, match="otro contrato económico"):
        service.evaluate_registered(
            confirmation_artifact={"economicContractFingerprint": "7" * 64},
            protocol_id="action-protocol-001",
            model_identity_attestation=identity.artifact,
        )
