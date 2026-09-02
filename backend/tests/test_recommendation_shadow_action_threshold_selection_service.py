from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_action_threshold_candidate_service import (
    RecommendationShadowActionThresholdCandidateService,
)
from app.services.recommendation_shadow_action_threshold_selection_service import (
    RecommendationShadowActionThresholdSelectionService,
)


class _IdentityPanelValidator:
    def validate_artifact(self, artifact):
        return artifact


class _MaliciousCandidateService:
    def generate(self, utility_panel):
        return {
            "sourceUtilityPanelFingerprint": utility_panel["utilityPanelFingerprint"],
            "economicContractFingerprint": utility_panel["economicContractFingerprint"],
            "candidateSetFingerprint": "c" * 64,
            "advisoryStatus": "no_advice",
            "productionEligible": True,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "selectedPolicy": None,
            "action": None,
            "policy": {
                "validationDataAccessedForCandidateGeneration": False,
                "trainRealizedOutcomesUsedForCandidateGeneration": False,
                "futureReserveConsumed": False,
            },
            "horizons": {},
        }


def _utility_row(*, candidate_id: int, signal: float, state: str, partition: str):
    realized = 0.08 if signal > 0 else -0.08 if signal < 0 else 0.0
    if state == "flat":
        utilities = {
            "hold": {"netRealizedExcessUtility": 0.0},
            "buy": {"netRealizedExcessUtility": realized - 0.001},
        }
    elif state == "reduced_long":
        utilities = {
            "hold": {"netRealizedExcessUtility": 0.5 * realized},
            "buy": {"netRealizedExcessUtility": realized - 0.001},
            "sell": {"netRealizedExcessUtility": -0.001},
        }
    else:
        utilities = {
            "hold": {"netRealizedExcessUtility": realized},
            "reduce": {"netRealizedExcessUtility": 0.5 * realized - 0.001},
            "sell": {"netRealizedExcessUtility": -0.001},
        }
    return {
        "partition": partition,
        "candidateId": candidate_id,
        "horizonDays": 30,
        "currentState": state,
        "expectedExcessReturn": signal,
        "realizedExcessReturn": realized,
        "allowedActionUtilities": utilities,
    }


def _panel(*, validation_source_rows: int = 12):
    states = ("flat", "reduced_long", "full_long")
    train = []
    for candidate_id, signal in enumerate((-0.08, -0.03, 0.02, 0.07), start=1):
        for state in states:
            train.append(
                _utility_row(
                    candidate_id=candidate_id,
                    signal=signal,
                    state=state,
                    partition="train",
                )
            )
    validation = []
    for offset in range(validation_source_rows):
        signal = -0.06 if offset % 2 == 0 else 0.06
        for state in states:
            validation.append(
                _utility_row(
                    candidate_id=100 + offset,
                    signal=signal,
                    state=state,
                    partition="validation",
                )
            )
    return {
        "utilityPanelFingerprint": "a" * 64,
        "economicContractFingerprint": "b" * 64,
        "positionStates": list(states),
        "requestedHorizons": [30],
        "trainUtilityRows": train,
        "validationUtilityRows": validation,
    }


def _service(**kwargs):
    return RecommendationShadowActionThresholdSelectionService(
        panel_validator=_IdentityPanelValidator(),
        candidate_service=RecommendationShadowActionThresholdCandidateService(
            panel_validator=_IdentityPanelValidator()
        ),
        **kwargs,
    )


def test_selects_only_generated_train_grid_policies_using_validation_utility():
    result = _service().select(_panel())

    assert result["status"] == "shadow_action_threshold_selection_frozen_for_future_confirmation"
    assert result["allRequestedHorizonsAndStatesSelected"] is True
    assert result["futureReserveConfirmationEligible"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["policy"]["candidateGenerationPartition"] == "train_signal_only"
    assert result["policy"]["candidateSelectionPartition"] == "validation_only"
    assert result["policy"]["futureReserveConsumed"] is False
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["policy"]["automaticTrading"] is False

    states = result["selections"]["30"]["states"]
    assert set(states) == {"flat", "reduced_long", "full_long"}
    assert all(payload["selectedPolicy"] is not None for payload in states.values())
    assert all(payload["validationRowCount"] == 12 for payload in states.values())


def test_train_realized_outcomes_cannot_change_selected_policy():
    baseline = _panel()
    changed = copy.deepcopy(baseline)
    for row in changed["trainUtilityRows"]:
        row["realizedExcessReturn"] = 999999.0
        row["allowedActionUtilities"] = {
            "fabricated": {"netRealizedExcessUtility": 999999.0}
        }

    first = _service().select(baseline)
    second = _service().select(changed)

    assert first["selections"] == second["selections"]
    assert first["selectionFingerprint"] == second["selectionFingerprint"]
    assert first["policy"]["trainRealizedOutcomesUsedForSelection"] is False


def test_insufficient_validation_keeps_future_reserve_confirmation_closed():
    result = _service(min_validation_rows_per_state=10).select(
        _panel(validation_source_rows=9)
    )

    assert result["status"] == "shadow_action_threshold_selection_insufficient"
    assert result["allRequestedHorizonsAndStatesSelected"] is False
    assert result["futureReserveConfirmationEligible"] is False
    assert all(
        payload["selectedPolicy"] is None
        for payload in result["selections"]["30"]["states"].values()
    )


def test_rejects_duplicate_validation_state_for_same_source_row():
    panel = _panel()
    panel["validationUtilityRows"].append(
        copy.deepcopy(panel["validationUtilityRows"][0])
    )

    with pytest.raises(ValueError, match="estado duplicado"):
        _service().select(panel)


def test_rejects_inconsistent_validation_signal_across_states():
    panel = _panel()
    row = next(
        item
        for item in panel["validationUtilityRows"]
        if item["candidateId"] == 100 and item["currentState"] == "full_long"
    )
    row["expectedExcessReturn"] = 123.0

    with pytest.raises(ValueError, match="señales inconsistentes"):
        _service().select(panel)


def test_rejects_candidate_layer_attempting_to_enable_production():
    service = RecommendationShadowActionThresholdSelectionService(
        panel_validator=_IdentityPanelValidator(),
        candidate_service=_MaliciousCandidateService(),
    )

    with pytest.raises(ValueError, match="productionEligible"):
        service.select(_panel())


def test_rejects_panel_validator_that_substitutes_artifact():
    class _ReplacingValidator:
        def validate_artifact(self, artifact):
            return copy.deepcopy(artifact)

    service = RecommendationShadowActionThresholdSelectionService(
        panel_validator=_ReplacingValidator()
    )

    with pytest.raises(ValueError, match="sustituyó"):
        service.select(_panel())


def test_invalid_minimum_validation_rows_fails_closed():
    for value in (True, 0, -1, 1.5):
        with pytest.raises(ValueError, match="entero positivo"):
            RecommendationShadowActionThresholdSelectionService(
                panel_validator=_IdentityPanelValidator(),
                min_validation_rows_per_state=value,
            )
