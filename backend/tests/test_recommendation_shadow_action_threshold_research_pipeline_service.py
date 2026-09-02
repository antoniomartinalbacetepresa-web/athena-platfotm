from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_action_threshold_research_pipeline_service import (
    RecommendationShadowActionThresholdResearchPipelineService,
)


class _SplitService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class _ContractService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class _ReadinessService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def assess(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def _split():
    return {"splitFingerprint": "a" * 64}


def _contract():
    return {"economicContractFingerprint": "b" * 64}


def _result():
    return {
        "sourceSplitFingerprint": "a" * 64,
        "economicContractFingerprint": "b" * 64,
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
            "thresholdFitting": "not_performed",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def test_pipeline_builds_split_and_contract_internally_before_readiness():
    split = _split()
    contract = _contract()
    result = _result()
    split_service = _SplitService(split)
    contract_service = _ContractService(contract)
    readiness_service = _ReadinessService(result)
    service = RecommendationShadowActionThresholdResearchPipelineService(
        split_service=split_service,
        economic_contract_service=contract_service,
        readiness_service=readiness_service,
    )
    train_end = datetime(2026, 3, 31, tzinfo=timezone.utc)
    validation_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    actual = service.evaluate(
        train_end=train_end,
        validation_end=validation_end,
        as_of=as_of,
        transaction_cost_bps=1.5,
        slippage_bps=2.0,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
        symbol="TEST",
        horizons=(30, 90),
    )

    assert actual is result
    assert split_service.calls == [
        {
            "train_end": train_end,
            "validation_end": validation_end,
            "as_of": as_of,
            "symbol": "TEST",
            "horizons": (30, 90),
        }
    ]
    assert contract_service.calls == [
        {
            "transaction_cost_bps": 1.5,
            "slippage_bps": 2.0,
            "objective_name": "net_excess_return_after_explicit_costs",
            "objective_version": "v1",
        }
    ]
    assert readiness_service.calls == [
        {"split": split, "economic_contract": contract}
    ]


def test_pipeline_rejects_readiness_from_another_split():
    result = _result()
    result["sourceSplitFingerprint"] = "c" * 64
    service = RecommendationShadowActionThresholdResearchPipelineService(
        split_service=_SplitService(_split()),
        economic_contract_service=_ContractService(_contract()),
        readiness_service=_ReadinessService(result),
    )

    with pytest.raises(ValueError, match="split producido"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            transaction_cost_bps=1.5,
            slippage_bps=2.0,
            objective_name="objective",
            objective_version="v1",
        )


def test_pipeline_rejects_readiness_from_another_economic_contract():
    result = _result()
    result["economicContractFingerprint"] = "c" * 64
    service = RecommendationShadowActionThresholdResearchPipelineService(
        split_service=_SplitService(_split()),
        economic_contract_service=_ContractService(_contract()),
        readiness_service=_ReadinessService(result),
    )

    with pytest.raises(ValueError, match="contrato económico"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            transaction_cost_bps=1.5,
            slippage_bps=2.0,
            objective_name="objective",
            objective_version="v1",
        )


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
def test_pipeline_fails_closed_on_premature_promotion(field, value):
    result = _result()
    result[field] = value
    service = RecommendationShadowActionThresholdResearchPipelineService(
        split_service=_SplitService(_split()),
        economic_contract_service=_ContractService(_contract()),
        readiness_service=_ReadinessService(result),
    )

    with pytest.raises(ValueError):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            transaction_cost_bps=1.5,
            slippage_bps=2.0,
            objective_name="objective",
            objective_version="v1",
        )


def test_pipeline_rejects_future_reserve_consumption():
    result = _result()
    result["policy"]["futureReserveConsumed"] = True
    service = RecommendationShadowActionThresholdResearchPipelineService(
        split_service=_SplitService(_split()),
        economic_contract_service=_ContractService(_contract()),
        readiness_service=_ReadinessService(result),
    )

    with pytest.raises(ValueError, match="reserva temporal"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            transaction_cost_bps=1.5,
            slippage_bps=2.0,
            objective_name="objective",
            objective_version="v1",
        )
