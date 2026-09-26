from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_action_threshold_candidate_service import (
    RecommendationShadowActionThresholdCandidateService,
)


class _IdentityPanelValidator:
    def validate_artifact(self, artifact):
        return artifact


def _expanded_row(*, candidate_id, signal, state, horizon=30, partition="train"):
    return {
        "partition": partition,
        "candidateId": candidate_id,
        "horizonDays": horizon,
        "currentState": state,
        "expectedExcessReturn": signal,
        "realizedExcessReturn": 0.123,
        "allowedActionUtilities": {"hold": {"netRealizedExcessUtility": 0.0}},
    }


def _panel(signals=(-0.05, 0.0, 0.08)):
    states = ("flat", "reduced_long", "full_long")
    train = []
    for candidate_id, signal in enumerate(signals, start=1):
        for state in states:
            train.append(_expanded_row(candidate_id=candidate_id, signal=signal, state=state))
    validation = [
        _expanded_row(
            candidate_id=99,
            signal=999.0,
            state=state,
            partition="validation",
        )
        for state in states
    ]
    return {
        "utilityPanelFingerprint": "a" * 64,
        "economicContractFingerprint": "b" * 64,
        "positionStates": list(states),
        "requestedHorizons": [30],
        "trainUtilityRows": train,
        "validationUtilityRows": validation,
    }


def _service(*, max_grid_points=11):
    return RecommendationShadowActionThresholdCandidateService(
        panel_validator=_IdentityPanelValidator(),
        max_grid_points=max_grid_points,
    )


def test_generates_state_conditional_candidates_from_train_signal_grid():
    result = _service().generate(_panel())
    horizon = result["horizons"]["30"]

    assert horizon["trainSignalGrid"] == [-0.05, 0.0, 0.08]
    assert horizon["candidatePolicyCountByState"] == {
        "flat": 3,
        "reduced_long": 3,
        "full_long": 3,
    }
    assert horizon["candidatePolicyCount"] == 9
    assert result["allRequestedHorizonsHaveStateCompleteCandidates"] is True
    assert result["status"] == "shadow_action_threshold_candidates_available"
    assert result["selectedPolicy"] is None
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["productionEligible"] is False


def test_validation_signal_cannot_create_or_change_candidate_policies():
    baseline_panel = _panel()
    changed_panel = copy.deepcopy(baseline_panel)
    changed_panel["validationUtilityRows"][0]["expectedExcessReturn"] = -999999.0
    changed_panel["validationUtilityRows"][1]["realizedExcessReturn"] = 999999.0

    baseline = _service().generate(baseline_panel)
    changed = _service().generate(changed_panel)

    assert baseline["horizons"]["30"]["trainSignalGrid"] == changed["horizons"]["30"]["trainSignalGrid"]
    assert baseline["horizons"]["30"]["candidatePolicies"] == changed["horizons"]["30"]["candidatePolicies"]
    assert baseline["policy"]["validationDataAccessedForCandidateGeneration"] is False


def test_train_realized_outcomes_cannot_change_candidate_policies():
    baseline_panel = _panel()
    changed_panel = copy.deepcopy(baseline_panel)
    for row in changed_panel["trainUtilityRows"]:
        row["realizedExcessReturn"] *= -1000.0
        row["allowedActionUtilities"] = {"fabricated": {"netRealizedExcessUtility": -999.0}}

    baseline = _service().generate(baseline_panel)
    changed = _service().generate(changed_panel)

    assert baseline["horizons"]["30"]["candidatePolicies"] == changed["horizons"]["30"]["candidatePolicies"]
    assert baseline["policy"]["trainRealizedOutcomesUsedForCandidateGeneration"] is False


def test_single_unique_train_signal_cannot_generate_three_action_state_thresholds():
    result = _service().generate(_panel(signals=(0.01, 0.01, 0.01)))
    horizon = result["horizons"]["30"]

    assert horizon["candidatePolicyCountByState"] == {
        "flat": 1,
        "reduced_long": 0,
        "full_long": 0,
    }
    assert horizon["allStatesHaveCandidates"] is False
    assert result["status"] == "shadow_action_threshold_candidates_insufficient"


def test_bounded_grid_is_deterministic_and_uses_only_train_distribution():
    signals = tuple(float(value) for value in range(100))
    first = _service(max_grid_points=5).generate(_panel(signals=signals))
    second = _service(max_grid_points=5).generate(_panel(signals=signals))

    grid = first["horizons"]["30"]["trainSignalGrid"]
    assert len(grid) == 5
    assert grid[0] == 0.0
    assert grid[-1] == 99.0
    assert first["horizons"]["30"]["candidatePolicies"] == second["horizons"]["30"]["candidatePolicies"]


def test_rejects_incomplete_state_expansion_for_a_source_row():
    panel = _panel()
    panel["trainUtilityRows"] = [
        row
        for row in panel["trainUtilityRows"]
        if not (row["candidateId"] == 1 and row["currentState"] == "full_long")
    ]

    with pytest.raises(ValueError, match="todos los estados"):
        _service().generate(panel)


def test_rejects_duplicate_state_expansion():
    panel = _panel()
    panel["trainUtilityRows"].append(copy.deepcopy(panel["trainUtilityRows"][0]))

    with pytest.raises(ValueError, match="estado duplicado"):
        _service().generate(panel)


def test_rejects_inconsistent_signal_across_states_for_same_source_row():
    panel = _panel()
    target = next(
        row
        for row in panel["trainUtilityRows"]
        if row["candidateId"] == 1 and row["currentState"] == "reduced_long"
    )
    target["expectedExcessReturn"] = 123.0

    with pytest.raises(ValueError, match="señales inconsistentes"):
        _service().generate(panel)


def test_candidate_policy_rules_never_include_disallowed_action_for_state():
    result = _service().generate(_panel())
    policies = result["horizons"]["30"]["candidatePolicies"]
    by_state = {state: [] for state in ("flat", "reduced_long", "full_long")}
    for policy in policies:
        by_state[policy["currentState"]].append(policy["decisionRule"])

    assert all("sell" not in rule and "reduce" not in rule for rule in by_state["flat"])
    assert all("reduce" not in rule for rule in by_state["reduced_long"])
    assert all("buy" not in rule for rule in by_state["full_long"])
