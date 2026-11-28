from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_action_uncertainty_evidence_service import (
    RecommendationActionUncertaintyEvidenceService,
)


SELECTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
AS_OF = datetime(2026, 4, 1, tzinfo=timezone.utc)
SELECTION_FP = "a" * 64
CONTRACT_FP = "b" * 64
PROTOCOL_FP = "c" * 64
REGISTRATION_FP = "d" * 64


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


def _policy(state: str, fingerprint_char: str) -> dict:
    if state == "flat":
        thresholds = {"buyAtOrAbove": 0.0}
    elif state == "reduced_long":
        thresholds = {"sellAtOrBelow": -0.02, "buyAtOrAbove": 0.02}
    else:
        thresholds = {"sellAtOrBelow": -0.03, "reduceAtOrBelow": -0.01}
    return {
        "currentState": state,
        "policyFingerprint": fingerprint_char * 64,
        "thresholds": thresholds,
        "decisionRule": "frozen_test_rule",
    }


POLICIES = {
    "flat": _policy("flat", "e"),
    "reduced_long": _policy("reduced_long", "f"),
    "full_long": _policy("full_long", "1"),
}


def _selection() -> dict:
    return {
        "selectionFingerprint": SELECTION_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "requestedHorizons": [30],
        "selections": {
            "30": {
                "horizonDays": 30,
                "states": {
                    state: {"selectedPolicy": copy.deepcopy(policy)}
                    for state, policy in POLICIES.items()
                },
            }
        },
    }


class _ProtocolRepository:
    def __init__(self, *, registered_at=SELECTED_AT - timedelta(days=1), minimum=0.015):
        self.record = {
            "registered_at": registered_at.isoformat(),
            "protocol": {
                "protocolId": "uncertainty-001",
                "protocolFingerprint": PROTOCOL_FP,
                "requiredHorizons": [30],
                "criteriaByHorizonAndState": {
                    "30": {
                        state: {
                            "confidenceMultiplier": 1.0,
                            "minimumLowerConfidenceBoundIncrementalUtilityVsHold": minimum,
                        }
                        for state in POLICIES
                    }
                },
            },
        }

    def get(self, *, protocol_id):
        return self.record if protocol_id == "uncertainty-001" else None

    def validate_record(self, record):
        return record


class _SelectionRepository:
    def __init__(self):
        self.record = {
            "selected_at": SELECTED_AT.isoformat(),
            "registration_fingerprint": REGISTRATION_FP,
            "selection": _selection(),
        }

    def get(self, *, selection_fingerprint):
        return self.record if selection_fingerprint == SELECTION_FP else None

    def validate_record(self, record):
        return record


class _ContractValidator:
    def validate(self, artifact):
        return artifact


class _UtilityService:
    def evaluate(self, *, economic_contract, current_state, realized_excess_return):
        realized = float(realized_excess_return)
        if current_state == "flat":
            allowed = {
                "hold": {"netRealizedExcessUtility": 0.0},
                "buy": {"netRealizedExcessUtility": realized},
            }
        elif current_state == "reduced_long":
            allowed = {
                "hold": {"netRealizedExcessUtility": 0.5 * realized},
                "buy": {"netRealizedExcessUtility": realized},
                "sell": {"netRealizedExcessUtility": 0.0},
            }
        else:
            allowed = {
                "hold": {"netRealizedExcessUtility": realized},
                "reduce": {"netRealizedExcessUtility": 0.5 * realized},
                "sell": {"netRealizedExcessUtility": 0.0},
            }
        return {
            "economicContractFingerprint": CONTRACT_FP,
            "currentState": current_state,
            "allowedActionUtilities": allowed,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "action": None,
            "automaticTrading": False,
        }


def _rows() -> list[dict]:
    result = []
    for index in range(20):
        candidate_as_of = SELECTED_AT + timedelta(days=index + 1)
        due_at = candidate_as_of + timedelta(days=30)
        signal = 0.04 if index % 2 == 0 else -0.04
        result.append(
            {
                "candidateId": index + 1,
                "horizonDays": 30,
                "candidateAsOf": candidate_as_of.isoformat(),
                "outcomeDueAt": due_at.isoformat(),
                "outcomeEvaluatedAt": (due_at + timedelta(hours=1)).isoformat(),
                "expectedExcessReturn": signal,
                "realizedExcessReturn": signal,
            }
        )
    return result


def _dataset() -> dict:
    rows = _rows()
    core = {
        "datasetVersion": "shadow-action-calibration-v2",
        "asOf": AS_OF.isoformat(),
        "symbol": None,
        "requestedHorizons": [30],
        "rowCount": len(rows),
        "rows": rows,
    }
    return {
        **core,
        "datasetFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "policy": {"automaticTrading": False},
    }


class _DatasetService:
    def __init__(self, dataset=None):
        self.dataset = dataset or _dataset()

    def build(self, *, as_of, symbol=None, horizons):
        result = copy.deepcopy(self.dataset)
        result["asOf"] = as_of.isoformat()
        result["symbol"] = symbol
        result["requestedHorizons"] = list(horizons)
        core = {
            "datasetVersion": result["datasetVersion"],
            "asOf": result["asOf"],
            "symbol": result["symbol"],
            "requestedHorizons": result["requestedHorizons"],
            "rowCount": result["rowCount"],
            "rows": result["rows"],
        }
        result["datasetFingerprint"] = _fingerprint(core)
        return result


def _confirmation() -> dict:
    states = {
        state: {
            "rowCount": 20,
            "selectedPolicyFingerprint": policy["policyFingerprint"],
            "meanIncrementalUtilityVsHold": 0.02,
        }
        for state, policy in POLICIES.items()
    }
    core = {
        "artifactVersion": "shadow-action-threshold-future-confirmation-v1",
        "selectionFingerprint": SELECTION_FP,
        "selectionRegistrationFingerprint": REGISTRATION_FP,
        "economicContractFingerprint": CONTRACT_FP,
        "selectedAt": SELECTED_AT.isoformat(),
        "asOf": AS_OF.isoformat(),
        "requestedHorizons": [30],
        "minimumSourceRowsPerHorizon": 20,
        "eligibleSourceRowCounts": {"30": 20},
        "horizons": {
            "30": {
                "horizonDays": 30,
                "sourceRowCount": 20,
                "states": states,
            }
        },
    }
    return {
        "status": "shadow_action_threshold_future_confirmation_sealed",
        **core,
        "confirmationFingerprint": _fingerprint(core),
        "futureConfirmationEvaluated": True,
        "firstMatureEvaluationSealed": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {"automaticTrading": False},
    }


def _service(*, protocol_repository=None, dataset_service=None):
    return RecommendationActionUncertaintyEvidenceService(
        protocol_repository=protocol_repository or _ProtocolRepository(),
        selection_repository=_SelectionRepository(),
        dataset_service=dataset_service or _DatasetService(),
        contract_validator=_ContractValidator(),
        utility_service=_UtilityService(),
    )


def test_precommitted_uncertainty_gate_reconstructs_first_seal_without_enabling_production():
    result = _service().evaluate_registered(
        confirmation_artifact=_confirmation(),
        protocol_id="uncertainty-001",
        economic_contract={"economicContractFingerprint": CONTRACT_FP},
    )

    assert result["status"] == "action_uncertainty_evidence_ready"
    assert result["actionUncertaintyEvidenceReady"] is True
    flat = result["horizons"]["30"]["states"]["flat"]
    assert flat["sampleStdDevIncrementalUtilityVsHold"] > 0.0
    assert flat["standardErrorIncrementalUtilityVsHold"] > 0.0
    assert flat["lowerConfidenceBoundIncrementalUtilityVsHold"] >= 0.015
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["codeDefaultConfidenceMultiplier"] is False


def test_protocol_registered_after_policy_freeze_fails_closed():
    service = _service(
        protocol_repository=_ProtocolRepository(
            registered_at=SELECTED_AT + timedelta(seconds=1)
        )
    )

    with pytest.raises(ValueError, match="después del freeze"):
        service.evaluate_registered(
            confirmation_artifact=_confirmation(),
            protocol_id="uncertainty-001",
            economic_contract={"economicContractFingerprint": CONTRACT_FP},
        )


def test_reconstructed_mean_must_match_first_seal():
    confirmation = _confirmation()
    confirmation["horizons"]["30"]["states"]["flat"][
        "meanIncrementalUtilityVsHold"
    ] = 0.5
    core_keys = (
        "artifactVersion",
        "selectionFingerprint",
        "selectionRegistrationFingerprint",
        "economicContractFingerprint",
        "selectedAt",
        "asOf",
        "requestedHorizons",
        "minimumSourceRowsPerHorizon",
        "eligibleSourceRowCounts",
        "horizons",
    )
    core = {key: confirmation[key] for key in core_keys}
    confirmation["confirmationFingerprint"] = _fingerprint(core)

    with pytest.raises(ValueError, match="media sellada"):
        _service().evaluate_registered(
            confirmation_artifact=confirmation,
            protocol_id="uncertainty-001",
            economic_contract={"economicContractFingerprint": CONTRACT_FP},
        )


def test_outcome_after_first_seal_cutoff_fails_closed():
    dataset = _dataset()
    dataset["rows"][0]["outcomeEvaluatedAt"] = (AS_OF + timedelta(seconds=1)).isoformat()
    service = _service(dataset_service=_DatasetService(dataset))

    with pytest.raises(ValueError, match="posterior al primer sello"):
        service.evaluate_registered(
            confirmation_artifact=_confirmation(),
            protocol_id="uncertainty-001",
            economic_contract={"economicContractFingerprint": CONTRACT_FP},
        )


def test_lower_bound_below_precommitted_minimum_is_insufficient_not_advice():
    service = _service(protocol_repository=_ProtocolRepository(minimum=0.03))

    result = service.evaluate_registered(
        confirmation_artifact=_confirmation(),
        protocol_id="uncertainty-001",
        economic_contract={"economicContractFingerprint": CONTRACT_FP},
    )

    assert result["status"] == "action_uncertainty_evidence_insufficient"
    assert result["actionUncertaintyEvidenceReady"] is False
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False
    assert "lower_bound_below_precommitted_minimum" in result["horizons"]["30"]["states"]["flat"]["blockers"]
