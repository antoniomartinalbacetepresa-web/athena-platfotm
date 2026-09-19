from __future__ import annotations

import math

import pytest

from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_shadow_action_economic_utility_service import (
    RecommendationShadowActionEconomicUtilityService,
)


def _contract(*, cost=10.0, slippage=5.0, reduced=0.5):
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=cost,
        slippage_bps=slippage,
        reduced_exposure_fraction=reduced,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )


def test_flat_positive_outcome_favors_buy_after_explicit_costs():
    result = RecommendationShadowActionEconomicUtilityService().evaluate(
        economic_contract=_contract(),
        current_state="flat",
        realized_excess_return=0.10,
    )
    assert set(result["allowedActionUtilities"]) == {"buy", "hold"}
    buy = result["allowedActionUtilities"]["buy"]
    hold = result["allowedActionUtilities"]["hold"]
    assert buy["absoluteExposureChange"] == pytest.approx(1.0)
    assert buy["transactionAndSlippageCost"] == pytest.approx(0.0015)
    assert buy["netRealizedExcessUtility"] == pytest.approx(0.0985)
    assert hold["netRealizedExcessUtility"] == pytest.approx(0.0)
    assert result["hindsightBestActions"] == ["buy"]
    assert result["action"] is None
    assert result["advisoryStatus"] == "no_advice"


def test_full_long_negative_outcome_favors_sell_without_using_future_as_live_feature():
    result = RecommendationShadowActionEconomicUtilityService().evaluate(
        economic_contract=_contract(),
        current_state="full_long",
        realized_excess_return=-0.10,
    )
    assert set(result["allowedActionUtilities"]) == {"hold", "reduce", "sell"}
    assert result["allowedActionUtilities"]["hold"]["netRealizedExcessUtility"] == pytest.approx(-0.10)
    assert result["allowedActionUtilities"]["reduce"]["netRealizedExcessUtility"] == pytest.approx(-0.05075)
    assert result["allowedActionUtilities"]["sell"]["netRealizedExcessUtility"] == pytest.approx(-0.0015)
    assert result["hindsightBestActions"] == ["sell"]
    assert result["labelSemantics"] == "matured_outcome_hindsight_counterfactual_not_live_feature"
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_reduced_long_positive_outcome_allows_buy_hold_sell_but_not_reduce():
    result = RecommendationShadowActionEconomicUtilityService().evaluate(
        economic_contract=_contract(reduced=0.4),
        current_state="reduced_long",
        realized_excess_return=0.02,
    )
    assert set(result["allowedActionUtilities"]) == {"buy", "hold", "sell"}
    assert result["allowedActionUtilities"]["hold"]["targetExposureFraction"] == pytest.approx(0.4)
    assert result["allowedActionUtilities"]["buy"]["absoluteExposureChange"] == pytest.approx(0.6)
    assert result["allowedActionUtilities"]["sell"]["absoluteExposureChange"] == pytest.approx(0.4)


def test_ties_are_preserved_instead_of_inventing_an_arbitrary_best_action():
    contract = _contract(cost=0.0, slippage=0.0)
    result = RecommendationShadowActionEconomicUtilityService().evaluate(
        economic_contract=contract,
        current_state="flat",
        realized_excess_return=0.0,
    )
    assert result["hindsightBestActions"] == ["buy", "hold"]
    assert result["bestNetRealizedExcessUtility"] == pytest.approx(0.0)


def test_costs_can_reverse_small_positive_signal_utility():
    result = RecommendationShadowActionEconomicUtilityService().evaluate(
        economic_contract=_contract(cost=10.0, slippage=10.0),
        current_state="flat",
        realized_excess_return=0.001,
    )
    assert result["allowedActionUtilities"]["buy"]["netRealizedExcessUtility"] == pytest.approx(-0.001)
    assert result["hindsightBestActions"] == ["hold"]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_rejects_nonfinite_realized_outcomes(value):
    with pytest.raises(ValueError, match="realized_excess_return"):
        RecommendationShadowActionEconomicUtilityService().evaluate(
            economic_contract=_contract(),
            current_state="flat",
            realized_excess_return=value,
        )


def test_rejects_state_not_defined_by_frozen_contract():
    with pytest.raises(ValueError, match="current_state"):
        RecommendationShadowActionEconomicUtilityService().evaluate(
            economic_contract=_contract(),
            current_state="short",
            realized_excess_return=0.1,
        )


def test_rejects_tampered_contract_before_computing_any_utility():
    contract = _contract()
    contract["positionStates"]["reduced_long"]["targetExposureFraction"] = 0.9
    with pytest.raises(ValueError, match="fingerprint"):
        RecommendationShadowActionEconomicUtilityService().evaluate(
            economic_contract=contract,
            current_state="full_long",
            realized_excess_return=0.1,
        )


def test_utility_fingerprint_binds_contract_state_and_realized_outcome():
    service = RecommendationShadowActionEconomicUtilityService()
    first = service.evaluate(
        economic_contract=_contract(), current_state="flat", realized_excess_return=0.1
    )
    second = service.evaluate(
        economic_contract=_contract(), current_state="flat", realized_excess_return=0.1
    )
    changed = service.evaluate(
        economic_contract=_contract(), current_state="flat", realized_excess_return=0.11
    )
    assert first["utilityFingerprint"] == second["utilityFingerprint"]
    assert first["utilityFingerprint"] != changed["utilityFingerprint"]
