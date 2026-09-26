from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_scenario_asymmetry_service import (
    RecommendationScenarioAsymmetryService,
    RecommendationScenarioInput,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


@dataclass(frozen=True)
class _ReverseResult:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _ReverseService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> _ReverseResult:
        self.calls.append(kwargs)
        return _ReverseResult(self.payload)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 7,
        "asOf": AS_OF.isoformat(),
        "latestPrice": 100.0,
        "annualDilutedEps": 5.0,
        "impliedEpsCagr": 0.12,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "policy": {"automaticTrading": False},
    }
    payload.update(overrides)
    return payload


def _scenario(name: str, growth: float, multiple: float) -> RecommendationScenarioInput:
    return RecommendationScenarioInput(
        name=name,
        eps_cagr=growth,
        exit_pe=multiple,
        available_at=AVAILABLE_AT,
        source=f"research_{name}",
        source_ref=f"scenario:{name}:v1",
    )


def _evaluate(service: RecommendationScenarioAsymmetryService, **overrides: object):
    kwargs: dict[str, object] = {
        "symbol": " AAPL ",
        "as_of": AS_OF,
        "horizon_years": 5,
        "required_return": 0.10,
        "bear": _scenario("bear", -0.05, 12.0),
        "base": _scenario("base", 0.10, 20.0),
        "bull": _scenario("bull", 0.20, 28.0),
    }
    kwargs.update(overrides)
    return service.evaluate(**kwargs)  # type: ignore[arg-type]


def test_scenario_asymmetry_calculates_probability_free_outcomes() -> None:
    upstream = _ReverseService(_payload())
    result = _evaluate(RecommendationScenarioAsymmetryService(reverse_valuation_service=upstream))

    assert result.status == "diagnostic_ready"
    assert result.symbol == "AAPL"
    assert len(result.scenarios) == 3
    assert [item.name for item in result.scenarios] == ["bear", "base", "bull"]
    assert result.scenarios[0].annualized_return <= result.scenarios[1].annualized_return
    assert result.scenarios[1].annualized_return <= result.scenarios[2].annualized_return
    assert result.production_eligible is False
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["probabilities"] == "not_assigned_no_expected_value_without_calibrated_probabilities"
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert upstream.calls == [
        {
            "symbol": "AAPL",
            "as_of": AS_OF,
            "horizon_years": 5,
            "required_return": 0.10,
            "exit_pe": 20.0,
        }
    ]


def test_scenario_asymmetry_rejects_lookahead_and_missing_provenance_before_upstream() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationScenarioAsymmetryService(reverse_valuation_service=upstream)

    future = RecommendationScenarioInput(
        name="bear",
        eps_cagr=-0.05,
        exit_pe=12.0,
        available_at=AS_OF + timedelta(seconds=1),
        source="research_bear",
        source_ref="scenario:bear:v1",
    )
    with pytest.raises(ValueError, match="look-ahead"):
        _evaluate(service, bear=future)

    missing = RecommendationScenarioInput(
        name="base",
        eps_cagr=0.10,
        exit_pe=20.0,
        available_at=AVAILABLE_AT,
        source="",
        source_ref="scenario:base:v1",
    )
    with pytest.raises(ValueError, match="provenance"):
        _evaluate(service, base=missing)
    assert upstream.calls == []


def test_scenario_asymmetry_rejects_non_finite_inputs_and_bad_labels() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationScenarioAsymmetryService(reverse_valuation_service=upstream)

    for value in (float("nan"), float("inf"), float("-inf")):
        bad = _scenario("bear", value, 12.0)
        with pytest.raises(ValueError, match="finito"):
            _evaluate(service, bear=bad)

    mislabeled = RecommendationScenarioInput(
        name="bull",
        eps_cagr=-0.05,
        exit_pe=12.0,
        available_at=AVAILABLE_AT,
        source="research_bear",
        source_ref="scenario:bear:v1",
    )
    with pytest.raises(ValueError, match="etiquetado"):
        _evaluate(service, bear=mislabeled)
    assert upstream.calls == []


def test_scenario_asymmetry_fails_closed_on_upstream_contract_violations() -> None:
    violations = (
        _payload(advisoryStatus="buy"),
        _payload(productionEligible=True),
        _payload(policy={"automaticTrading": True}),
        _payload(symbol="MSFT"),
        _payload(asOf=(AS_OF + timedelta(seconds=1)).isoformat()),
    )
    for payload in violations:
        service = RecommendationScenarioAsymmetryService(
            reverse_valuation_service=_ReverseService(payload)
        )
        with pytest.raises(RuntimeError):
            _evaluate(service)


def test_scenario_asymmetry_preserves_not_ready_without_inventing_outcomes() -> None:
    result = _evaluate(
        RecommendationScenarioAsymmetryService(
            reverse_valuation_service=_ReverseService(
                _payload(status="valuation_evidence_not_ready", latestPrice=None, annualDilutedEps=None)
            )
        )
    )

    assert result.status == "valuation_evidence_not_ready"
    assert result.scenarios == ()
    assert result.upside_downside_ratio is None
    assert result.production_eligible is False


def test_scenario_asymmetry_rejects_misordered_bear_base_bull_outcomes() -> None:
    service = RecommendationScenarioAsymmetryService(
        reverse_valuation_service=_ReverseService(_payload())
    )
    with pytest.raises(ValueError, match="bear <= base <= bull"):
        _evaluate(
            service,
            bear=_scenario("bear", 0.30, 30.0),
            base=_scenario("base", 0.10, 20.0),
            bull=_scenario("bull", 0.20, 28.0),
        )
