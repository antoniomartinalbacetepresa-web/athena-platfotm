from __future__ import annotations

import math

import pytest

from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


def _service() -> RecommendationShadowActionEconomicContractService:
    return RecommendationShadowActionEconomicContractService()


def _contract():
    return _service().build(
        transaction_cost_bps=1.5,
        slippage_bps=2.0,
        reduced_exposure_fraction=0.5,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )


def _refingerprint(service, artifact):
    core = {
        key: artifact[key]
        for key in (
            "artifactVersion",
            "portfolioModel",
            "positionStates",
            "actions",
            "economicObjective",
            "constraints",
        )
    }
    artifact["economicContractFingerprint"] = service._fingerprint(core)


def test_build_creates_explicit_long_only_target_exposure_contract():
    artifact = _contract()
    assert artifact["portfolioModel"] == "long_only_single_asset_target_exposure"
    assert artifact["positionStates"] == {
        "flat": {"targetExposureFraction": 0.0},
        "reduced_long": {"targetExposureFraction": 0.5},
        "full_long": {"targetExposureFraction": 1.0},
    }
    assert artifact["actions"]["buy"]["allowedFrom"] == ["flat", "reduced_long"]
    assert artifact["actions"]["reduce"]["allowedFrom"] == ["full_long"]
    assert artifact["actions"]["reduce"]["targetExposureFraction"] == pytest.approx(0.5)
    assert artifact["actions"]["sell"]["allowedFrom"] == ["reduced_long", "full_long"]
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["actionThresholds"] is None
    assert artifact["action"] is None


def test_build_requires_explicit_cost_slippage_and_reduced_exposure():
    artifact = _contract()
    objective = artifact["economicObjective"]
    assert objective["transactionCostBps"] == pytest.approx(1.5)
    assert objective["slippageBps"] == pytest.approx(2.0)
    assert objective["costAssumptionsSource"] == "caller_precommitted_research_protocol"
    assert artifact["constraints"]["futureTemporalReserveConsumed"] is False
    assert artifact["constraints"]["automaticTrading"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_cost_bps", -0.1),
        ("transaction_cost_bps", math.nan),
        ("transaction_cost_bps", math.inf),
        ("slippage_bps", -0.1),
        ("slippage_bps", math.nan),
        ("slippage_bps", math.inf),
        ("reduced_exposure_fraction", 0.0),
        ("reduced_exposure_fraction", 1.0),
        ("reduced_exposure_fraction", -0.1),
        ("reduced_exposure_fraction", math.nan),
    ],
)
def test_build_rejects_invalid_economic_inputs(field, value):
    kwargs = {
        "transaction_cost_bps": 1.0,
        "slippage_bps": 2.0,
        "reduced_exposure_fraction": 0.5,
        "objective_name": "net_excess_return_after_explicit_costs",
        "objective_version": "v1",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        _service().build(**kwargs)


@pytest.mark.parametrize("field", ["objective_name", "objective_version"])
def test_build_rejects_missing_objective_identity(field):
    kwargs = {
        "transaction_cost_bps": 1.0,
        "slippage_bps": 2.0,
        "reduced_exposure_fraction": 0.5,
        "objective_name": "net_excess_return_after_explicit_costs",
        "objective_version": "v1",
    }
    kwargs[field] = "  "
    with pytest.raises(ValueError):
        _service().build(**kwargs)


def test_validate_accepts_exact_immutable_artifact():
    artifact = _contract()
    assert _service().validate(artifact) is artifact


def test_validate_detects_unhashed_semantic_tampering():
    artifact = _contract()
    artifact["actions"]["sell"]["allowedFrom"] = ["flat", "full_long"]
    with pytest.raises(ValueError, match="fingerprint"):
        _service().validate(artifact)


def test_validate_rejects_rehashed_action_meaning_tampering():
    service = _service()
    artifact = _contract()
    artifact["actions"]["sell"]["meaning"] = "open_short_position"
    _refingerprint(service, artifact)
    with pytest.raises(ValueError, match="semántica exacta"):
        service.validate(artifact)


def test_validate_rejects_rehashed_reduced_target_inconsistency():
    service = _service()
    artifact = _contract()
    artifact["actions"]["reduce"]["targetExposureFraction"] = 0.25
    _refingerprint(service, artifact)
    with pytest.raises(ValueError, match="semántica exacta"):
        service.validate(artifact)


def test_validate_rejects_attempt_to_enable_trading_even_if_refingerprinted():
    service = _service()
    artifact = _contract()
    artifact["constraints"]["automaticTrading"] = True
    _refingerprint(service, artifact)
    with pytest.raises(ValueError, match="capacidad prohibida"):
        service.validate(artifact)


def test_validate_rejects_unexpected_objective_fields_even_if_refingerprinted():
    service = _service()
    artifact = _contract()
    artifact["economicObjective"]["hiddenPenalty"] = -100.0
    _refingerprint(service, artifact)
    with pytest.raises(ValueError, match="campos no permitidos"):
        service.validate(artifact)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("actionThresholds", {"buy": 0.03}),
        ("action", "buy"),
        ("score", 0.8),
        ("conviction", 0.7),
    ],
)
def test_validate_fails_closed_on_promotion_or_calibration_payload(field, value):
    artifact = _contract()
    artifact[field] = value
    with pytest.raises(ValueError):
        _service().validate(artifact)


def test_fingerprint_changes_with_any_precommitted_economic_assumption():
    service = _service()
    first = _contract()
    different_cost = service.build(
        transaction_cost_bps=1.6,
        slippage_bps=2.0,
        reduced_exposure_fraction=0.5,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )
    different_reduction = service.build(
        transaction_cost_bps=1.5,
        slippage_bps=2.0,
        reduced_exposure_fraction=0.4,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )
    assert first["economicContractFingerprint"] != different_cost["economicContractFingerprint"]
    assert first["economicContractFingerprint"] != different_reduction["economicContractFingerprint"]
