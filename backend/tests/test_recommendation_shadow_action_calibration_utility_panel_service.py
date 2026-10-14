from __future__ import annotations

import math

import pytest

from app.services.recommendation_shadow_action_calibration_utility_panel_service import (
    RecommendationShadowActionCalibrationUtilityPanelService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


class _IdentitySplitValidator:
    def validate_artifact(self, artifact):
        return artifact


class _IdentitySemanticValidator:
    def validate(self, artifact):
        return artifact


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=10.0,
        slippage_bps=5.0,
        reduced_exposure_fraction=0.5,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )


def _row(*, candidate_id, horizon, expected, realized, symbol="TEST"):
    return {
        "candidateId": candidate_id,
        "symbol": symbol,
        "horizonDays": horizon,
        "candidateAsOf": "2026-01-01T00:00:00+00:00",
        "outcomeDueAt": "2026-01-31T00:00:00+00:00",
        "outcomeEvaluatedAt": "2026-02-01T00:00:00+00:00",
        "expectedExcessReturn": expected,
        "realizedExcessReturn": realized,
    }


def _split():
    return {
        "splitFingerprint": "a" * 64,
        "requestedHorizons": [30],
        "reservedFutureRowCount": 7,
        "trainRows": [
            _row(candidate_id=1, horizon=30, expected=0.08, realized=0.10),
        ],
        "validationRows": [
            _row(candidate_id=2, horizon=30, expected=-0.04, realized=-0.06),
        ],
    }


def _service():
    return RecommendationShadowActionCalibrationUtilityPanelService(
        split_validator=_IdentitySplitValidator(),
        semantic_validator=_IdentitySemanticValidator(),
    )


def test_panel_evaluates_every_contract_state_for_each_matured_row():
    result = _service().build(split=_split(), economic_contract=_contract())
    assert result["positionStates"] == ["flat", "reduced_long", "full_long"]
    assert result["trainSourceRowCount"] == 1
    assert result["validationSourceRowCount"] == 1
    assert result["trainUtilityRowCount"] == 3
    assert result["validationUtilityRowCount"] == 3
    assert {row["currentState"] for row in result["trainUtilityRows"]} == {
        "flat",
        "reduced_long",
        "full_long",
    }
    assert {row["currentState"] for row in result["validationUtilityRows"]} == {
        "flat",
        "reduced_long",
        "full_long",
    }


def test_panel_preserves_signal_and_matured_outcome_but_does_not_fabricate_portfolio_history():
    result = _service().build(split=_split(), economic_contract=_contract())
    flat = next(row for row in result["trainUtilityRows"] if row["currentState"] == "flat")
    assert flat["expectedExcessReturn"] == pytest.approx(0.08)
    assert flat["realizedExcessReturn"] == pytest.approx(0.10)
    assert flat["hindsightBestActions"] == ["buy"]
    assert result["labelSemantics"] == (
        "matured_outcome_state_counterfactuals_not_observed_portfolio_history"
    )
    assert result["policy"]["portfolioHistoryFabricated"] is False
    assert result["action"] is None
    assert result["productionEligible"] is False


def test_panel_never_exposes_reserved_future_rows():
    result = _service().build(split=_split(), economic_contract=_contract())
    assert result["sourceReservedFutureRowCount"] == 7
    assert result["policy"]["futureReserveConsumed"] is False
    assert "futureRows" not in result
    assert all(
        row["partition"] in {"train", "validation"}
        for row in result["trainUtilityRows"] + result["validationUtilityRows"]
    )


def test_panel_uses_state_conditional_action_sets():
    result = _service().build(split=_split(), economic_contract=_contract())
    rows = {row["currentState"]: row for row in result["trainUtilityRows"]}
    assert set(rows["flat"]["allowedActionUtilities"]) == {"buy", "hold"}
    assert set(rows["reduced_long"]["allowedActionUtilities"]) == {"buy", "hold", "sell"}
    assert set(rows["full_long"]["allowedActionUtilities"]) == {"hold", "reduce", "sell"}


def test_panel_rejects_tampered_economic_contract_before_label_generation():
    contract = _contract()
    contract["positionStates"]["reduced_long"]["targetExposureFraction"] = 0.9
    with pytest.raises(ValueError, match="fingerprint"):
        _service().build(split=_split(), economic_contract=contract)


@pytest.mark.parametrize("field", ["expectedExcessReturn", "realizedExcessReturn"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_panel_rejects_nonfinite_signal_or_outcome(field, value):
    split = _split()
    split["trainRows"][0][field] = value
    with pytest.raises(ValueError, match=field):
        _service().build(split=split, economic_contract=_contract())


def test_panel_fingerprint_binds_split_contract_and_counterfactual_labels():
    first = _service().build(split=_split(), economic_contract=_contract())
    second = _service().build(split=_split(), economic_contract=_contract())
    changed_contract = RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=10.0,
        slippage_bps=5.0,
        reduced_exposure_fraction=0.4,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )
    changed = _service().build(split=_split(), economic_contract=changed_contract)
    assert first["utilityPanelFingerprint"] == second["utilityPanelFingerprint"]
    assert first["utilityPanelFingerprint"] != changed["utilityPanelFingerprint"]


def test_validate_artifact_accepts_exact_panel():
    service = _service()
    panel = service.build(split=_split(), economic_contract=_contract())
    assert service.validate_artifact(panel) is panel


def test_validate_artifact_detects_utility_tampering():
    service = _service()
    panel = service.build(split=_split(), economic_contract=_contract())
    panel["trainUtilityRows"][0]["expectedExcessReturn"] = 999.0
    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(panel)


def test_validate_artifact_rejects_promotion_even_outside_fingerprinted_core():
    service = _service()
    panel = service.build(split=_split(), economic_contract=_contract())
    panel["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible"):
        service.validate_artifact(panel)


def test_validate_artifact_rejects_partition_relabeling_after_refingerprint():
    service = _service()
    panel = service.build(split=_split(), economic_contract=_contract())
    panel["trainUtilityRows"][0]["partition"] = "validation"
    core_keys = (
        "artifactVersion",
        "sourceSplitFingerprint",
        "economicContractFingerprint",
        "positionStates",
        "requestedHorizons",
        "trainSourceRowCount",
        "validationSourceRowCount",
        "trainUtilityRowCount",
        "validationUtilityRowCount",
        "sourceReservedFutureRowCount",
        "trainUtilityRows",
        "validationUtilityRows",
    )
    panel["utilityPanelFingerprint"] = service._fingerprint(
        {key: panel.get(key) for key in core_keys}
    )
    with pytest.raises(ValueError, match="otra partición"):
        service.validate_artifact(panel)


class _ReplacingSplitValidator:
    def validate_artifact(self, artifact):
        return dict(artifact)


def test_panel_fails_closed_if_validator_substitutes_split():
    service = RecommendationShadowActionCalibrationUtilityPanelService(
        split_validator=_ReplacingSplitValidator(),
        semantic_validator=_IdentitySemanticValidator(),
    )
    with pytest.raises(ValueError, match="sustituyó"):
        service.build(split=_split(), economic_contract=_contract())
