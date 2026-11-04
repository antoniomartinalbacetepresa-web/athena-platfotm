from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_action_threshold_future_confirmation_service import (
    RecommendationShadowActionThresholdFutureConfirmationService,
)


SELECTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


class _SelectionRepository:
    def __init__(self, record=None):
        self.record = record

    def get(self, *, selection_fingerprint):
        if self.record is None:
            return None
        if self.record["selection_fingerprint"] != selection_fingerprint:
            return None
        return self.record

    def validate_record(self, record):
        return record


class _ConfirmationRepository:
    def __init__(self):
        self.record = None
        self.seal_calls = 0

    def get(self, *, selection_fingerprint):
        if self.record is None:
            return None
        if self.record["selection_fingerprint"] != selection_fingerprint:
            return None
        return self.record

    def seal(self, *, selection_fingerprint, confirmation, sealed_at):
        self.seal_calls += 1
        if self.record is None:
            self.record = {
                "selection_fingerprint": selection_fingerprint,
                "sealed_at": sealed_at.isoformat(),
                "confirmation": copy.deepcopy(confirmation),
                "confirmation_fingerprint": hashlib.sha256(
                    json.dumps(
                        confirmation,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest(),
            }
        return self.record

    def validate_record(self, record):
        return record


class _DatasetService:
    def __init__(self, dataset):
        self.dataset = dataset
        self.calls = 0

    def build(self, *, as_of, symbol=None, horizons):
        self.calls += 1
        result = copy.deepcopy(self.dataset)
        result["asOf"] = as_of.isoformat()
        result["symbol"] = symbol
        result["requestedHorizons"] = list(horizons)
        _refresh_dataset_fingerprint(result)
        return result


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
            "economicContractFingerprint": economic_contract[
                "economicContractFingerprint"
            ],
            "currentState": current_state,
            "allowedActionUtilities": allowed,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "action": None,
            "automaticTrading": False,
        }


def _policy(state, thresholds, fingerprint_char):
    return {
        "currentState": state,
        "policyFingerprint": fingerprint_char * 64,
        "thresholds": thresholds,
        "decisionRule": "frozen_test_rule",
    }


def _selection():
    states = {
        "flat": {
            "status": "validation_selected_shadow_policy",
            "selectedPolicy": _policy("flat", {"buyAtOrAbove": 0.0}, "c"),
        },
        "reduced_long": {
            "status": "validation_selected_shadow_policy",
            "selectedPolicy": _policy(
                "reduced_long",
                {"sellAtOrBelow": -0.02, "buyAtOrAbove": 0.02},
                "e",
            ),
        },
        "full_long": {
            "status": "validation_selected_shadow_policy",
            "selectedPolicy": _policy(
                "full_long",
                {"sellAtOrBelow": -0.03, "reduceAtOrBelow": -0.01},
                "f",
            ),
        },
    }
    return {
        "status": "shadow_action_threshold_selection_frozen_for_future_confirmation",
        "selectionFingerprint": "a" * 64,
        "economicContractFingerprint": "b" * 64,
        "requestedHorizons": [30],
        "futureReserveConfirmationEligible": True,
        "selections": {
            "30": {
                "horizonDays": 30,
                "allStatesSelected": True,
                "states": states,
            }
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "futureReserveConsumed": False,
            "selectedResearchThresholdsMayBeRefitOnFutureReserve": False,
        },
    }


def _selection_record():
    return {
        "selection_fingerprint": "a" * 64,
        "selected_at": SELECTED_AT.isoformat(),
        "selection": _selection(),
        "registration_fingerprint": "d" * 64,
    }


def _contract():
    return {"economicContractFingerprint": "b" * 64}


def _row(index, *, signal=None, realized=None, candidate_as_of=None):
    candidate_time = candidate_as_of or (SELECTED_AT + timedelta(days=index + 1))
    due = candidate_time + timedelta(days=30)
    evaluated = due + timedelta(hours=1)
    signal_value = (0.05 if index % 2 == 0 else -0.05) if signal is None else signal
    realized_value = signal_value if realized is None else realized
    return {
        "candidateId": index + 1,
        "horizonDays": 30,
        "candidateAsOf": candidate_time.isoformat(),
        "outcomeDueAt": due.isoformat(),
        "outcomeEvaluatedAt": evaluated.isoformat(),
        "expectedExcessReturn": signal_value,
        "realizedExcessReturn": realized_value,
    }


def _dataset(row_count):
    rows = [_row(index) for index in range(row_count)]
    result = {
        "datasetVersion": "shadow-action-calibration-v2",
        "asOf": AS_OF.isoformat(),
        "symbol": None,
        "requestedHorizons": [30],
        "rowCount": len(rows),
        "rows": rows,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "evidenceSource": "trusted_persisted_live_cycle_attestation_v1_only",
            "researchHoldoutReuse": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }
    _refresh_dataset_fingerprint(result)
    return result


def _refresh_dataset_fingerprint(dataset):
    dataset["rowCount"] = len(dataset["rows"])
    core = {
        "datasetVersion": dataset["datasetVersion"],
        "asOf": dataset["asOf"],
        "symbol": dataset["symbol"],
        "requestedHorizons": dataset["requestedHorizons"],
        "rowCount": dataset["rowCount"],
        "rows": dataset["rows"],
    }
    dataset["datasetFingerprint"] = hashlib.sha256(
        json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _service(dataset, *, confirmation_repository=None, selection_record=None):
    confirmation_repo = confirmation_repository or _ConfirmationRepository()
    return (
        RecommendationShadowActionThresholdFutureConfirmationService(
            selection_repository=_SelectionRepository(
                _selection_record() if selection_record is None else selection_record
            ),
            confirmation_repository=confirmation_repo,
            dataset_service=_DatasetService(dataset),
            contract_validator=_ContractValidator(),
            utility_service=_UtilityService(),
        ),
        confirmation_repo,
    )


def test_pending_confirmation_exposes_counts_but_no_performance():
    service, repo = _service(_dataset(19))

    result = service.evaluate(
        selection_fingerprint="a" * 64,
        economic_contract=_contract(),
        as_of=AS_OF,
    )

    assert result["status"] == "shadow_action_threshold_future_confirmation_pending"
    assert result["eligibleSourceRowCounts"] == {"30": 19}
    assert result["performanceMetricsExposed"] is False
    assert result["futureConfirmationEvaluated"] is False
    assert result["futureConfirmationPassed"] is None
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert repo.seal_calls == 0


def test_first_mature_confirmation_is_evaluated_and_sealed():
    service, repo = _service(_dataset(20))

    result = service.evaluate(
        selection_fingerprint="a" * 64,
        economic_contract=_contract(),
        as_of=AS_OF,
    )

    assert result["status"] == "shadow_action_threshold_future_confirmation_sealed"
    assert result["eligibleSourceRowCounts"] == {"30": 20}
    assert result["performanceMetricsExposed"] is True
    assert result["futureConfirmationEvaluated"] is True
    assert result["firstMatureEvaluationSealed"] is True
    assert result["futureConfirmationPassed"] is None
    assert result["formalStatisticalPromotionGateImplemented"] is False
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["action"] is None
    assert result["policy"]["thresholdRefitAllowed"] is False
    assert result["policy"]["policyReselectionAllowed"] is False
    assert result["policy"]["automaticTrading"] is False
    assert set(result["horizons"]["30"]["states"]) == {
        "flat",
        "reduced_long",
        "full_long",
    }
    assert repo.seal_calls == 1


def test_later_more_favorable_evidence_cannot_replace_first_seal():
    repo = _ConfirmationRepository()
    first_service, _ = _service(_dataset(20), confirmation_repository=repo)
    first = first_service.evaluate(
        selection_fingerprint="a" * 64,
        economic_contract=_contract(),
        as_of=AS_OF,
    )

    later_dataset = _dataset(30)
    for row in later_dataset["rows"]:
        row["realizedExcessReturn"] = 1000.0
    _refresh_dataset_fingerprint(later_dataset)
    later_service, _ = _service(later_dataset, confirmation_repository=repo)
    second = later_service.evaluate(
        selection_fingerprint="a" * 64,
        economic_contract=_contract(),
        as_of=AS_OF + timedelta(days=60),
    )

    assert second == first
    assert repo.seal_calls == 1


def test_pre_freeze_rows_do_not_count_toward_maturity():
    dataset = _dataset(20)
    dataset["rows"][0] = _row(
        0,
        candidate_as_of=SELECTED_AT - timedelta(days=40),
    )
    _refresh_dataset_fingerprint(dataset)
    service, _ = _service(dataset)

    result = service.evaluate(
        selection_fingerprint="a" * 64,
        economic_contract=_contract(),
        as_of=AS_OF,
    )

    assert result["status"] == "shadow_action_threshold_future_confirmation_pending"
    assert result["eligibleSourceRowCounts"] == {"30": 19}


def test_outcome_evaluated_before_due_fails_closed():
    dataset = _dataset(20)
    row = dataset["rows"][0]
    row["outcomeEvaluatedAt"] = (
        datetime.fromisoformat(row["outcomeDueAt"]) - timedelta(seconds=1)
    ).isoformat()
    _refresh_dataset_fingerprint(dataset)
    service, _ = _service(dataset)

    with pytest.raises(ValueError, match="antes de madurar"):
        service.evaluate(
            selection_fingerprint="a" * 64,
            economic_contract=_contract(),
            as_of=AS_OF,
        )


def test_dataset_production_escape_fails_closed():
    dataset = _dataset(20)
    dataset["productionEligible"] = True
    service, _ = _service(dataset)

    with pytest.raises(ValueError, match="productionEligible"):
        service.evaluate(
            selection_fingerprint="a" * 64,
            economic_contract=_contract(),
            as_of=AS_OF,
        )


def test_economic_contract_must_match_frozen_selection():
    service, _ = _service(_dataset(20))
    contract = {"economicContractFingerprint": "9" * 64}

    with pytest.raises(ValueError, match="no coincide"):
        service.evaluate(
            selection_fingerprint="a" * 64,
            economic_contract=contract,
            as_of=AS_OF,
        )


def test_confirmation_requires_previously_frozen_selection():
    service, _ = _service(_dataset(20), selection_record=False)
    service._selection_repository.record = None

    with pytest.raises(ValueError, match="no fue congelada"):
        service.evaluate(
            selection_fingerprint="a" * 64,
            economic_contract=_contract(),
            as_of=AS_OF,
        )


def test_as_of_must_be_after_immutable_selection_boundary():
    service, _ = _service(_dataset(20))

    with pytest.raises(ValueError, match="posterior"):
        service.evaluate(
            selection_fingerprint="a" * 64,
            economic_contract=_contract(),
            as_of=SELECTED_AT,
        )
