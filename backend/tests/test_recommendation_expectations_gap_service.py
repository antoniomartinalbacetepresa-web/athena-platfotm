from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_expectations_gap_service import (
    RecommendationExpectationsGapService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


@dataclass(frozen=True)
class _ReverseDiagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _ReverseService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> _ReverseDiagnostic:
        self.calls.append(kwargs)
        return _ReverseDiagnostic(self.payload)


def _payload(
    *,
    status: str = "diagnostic_ready",
    implied_eps_cagr: float | None = 0.12,
    advisory_status: str = "no_advice",
    production_eligible: bool = False,
    automatic_trading: bool = False,
    symbol: str = "AAPL",
    as_of: datetime = AS_OF,
) -> dict[str, object]:
    return {
        "status": status,
        "symbol": symbol,
        "instrumentId": 7,
        "asOf": as_of.isoformat(),
        "impliedEpsCagr": implied_eps_cagr,
        "advisoryStatus": advisory_status,
        "productionEligible": production_eligible,
        "policy": {"automaticTrading": automatic_trading},
    }


def _evaluate(
    service: RecommendationExpectationsGapService,
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "symbol": " AAPL ",
        "as_of": AS_OF,
        "horizon_years": 5,
        "required_return": 0.10,
        "exit_pe": 20.0,
        "reference_eps_cagr": 0.15,
        "expectation_kind": "company_guidance",
        "expectation_metric": "eps_cagr",
        "expectation_horizon_years": 5,
        "expectation_available_at": AVAILABLE_AT,
        "expectation_source": "sec_company_guidance",
        "expectation_source_ref": "filing:0000320193-25-000079#guidance",
    }
    kwargs.update(overrides)
    return service.evaluate(**kwargs)  # type: ignore[arg-type]


def test_expectations_gap_compares_typed_pit_reference_with_price_implied_hurdle() -> None:
    upstream = _ReverseService(_payload(implied_eps_cagr=0.12))
    result = _evaluate(RecommendationExpectationsGapService(reverse_valuation_service=upstream))

    assert result.status == "diagnostic_ready"
    assert result.symbol == "AAPL"
    assert result.expectations_gap == pytest.approx(0.03)
    assert result.production_eligible is False
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["comparability"] == "exact_metric_and_horizon_required"
    assert payload["policy"]["crossKindAggregation"] == "forbidden_until_separately_calibrated"
    assert payload["referenceExpectation"] == {
        "kind": "company_guidance",
        "metric": "eps_cagr",
        "horizonYears": 5,
        "epsCagr": 0.15,
        "availableAt": AVAILABLE_AT.isoformat(),
        "source": "sec_company_guidance",
        "sourceRef": "filing:0000320193-25-000079#guidance",
    }
    assert upstream.calls == [
        {
            "symbol": "AAPL",
            "as_of": AS_OF,
            "horizon_years": 5,
            "required_return": 0.10,
            "exit_pe": 20.0,
        }
    ]


def test_expectations_gap_rejects_incomparable_expectation_kinds_metrics_and_horizons() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    with pytest.raises(ValueError, match="expectation_kind no soportado"):
        _evaluate(service, expectation_kind="blended_guess")
    with pytest.raises(ValueError, match="expectation_metric debe ser eps_cagr"):
        _evaluate(service, expectation_metric="revenue_cagr")
    with pytest.raises(ValueError, match="coincidir exactamente"):
        _evaluate(service, expectation_horizon_years=3)
    assert upstream.calls == []


def test_expectations_gap_accepts_each_kind_without_cross_kind_aggregation() -> None:
    for kind in (
        "company_guidance",
        "analyst_consensus",
        "internal_model",
        "historical_run_rate",
    ):
        result = _evaluate(
            RecommendationExpectationsGapService(
                reverse_valuation_service=_ReverseService(_payload())
            ),
            expectation_kind=kind,
        )
        payload = result.to_api_dict()
        assert payload["referenceExpectation"]["kind"] == kind
        assert payload["policy"]["crossKindAggregation"] == "forbidden_until_separately_calibrated"


def test_expectations_gap_rejects_invalid_reference_horizon_before_upstream() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    for value in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="entero positivo"):
            _evaluate(service, expectation_horizon_years=value)
    assert upstream.calls == []


def test_expectations_gap_rejects_lookahead_before_upstream_call() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    with pytest.raises(ValueError, match="look-ahead"):
        _evaluate(
            service,
            expectation_available_at=AS_OF + timedelta(microseconds=1),
        )
    assert upstream.calls == []


def test_expectations_gap_requires_timezone_aware_cutoffs() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    with pytest.raises(ValueError, match="as_of.*zona horaria"):
        _evaluate(service, as_of=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="expectation_available_at.*zona horaria"):
        _evaluate(service, expectation_available_at=datetime(2025, 12, 31, 23))
    assert upstream.calls == []


def test_expectations_gap_rejects_non_finite_reference_and_missing_provenance() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finito"):
            _evaluate(service, reference_eps_cagr=value)

    with pytest.raises(ValueError, match="expectation_source.*provenance"):
        _evaluate(service, expectation_source=" ")
    with pytest.raises(ValueError, match="expectation_source_ref.*provenance"):
        _evaluate(service, expectation_source_ref="")
    assert upstream.calls == []


def test_expectations_gap_fails_closed_on_upstream_policy_violations() -> None:
    violations = (
        _payload(advisory_status="buy"),
        _payload(production_eligible=True),
        _payload(automatic_trading=True),
        _payload(symbol="MSFT"),
        _payload(as_of=AS_OF + timedelta(seconds=1)),
    )

    for payload in violations:
        service = RecommendationExpectationsGapService(
            reverse_valuation_service=_ReverseService(payload)
        )
        with pytest.raises(RuntimeError):
            _evaluate(service)


def test_expectations_gap_rejects_non_finite_upstream_growth() -> None:
    service = RecommendationExpectationsGapService(
        reverse_valuation_service=_ReverseService(
            _payload(implied_eps_cagr=float("nan"))
        )
    )
    with pytest.raises(ValueError, match="impliedEpsCagr.*finito"):
        _evaluate(service)


def test_expectations_gap_preserves_not_ready_state_without_inventing_gap() -> None:
    result = _evaluate(
        RecommendationExpectationsGapService(
            reverse_valuation_service=_ReverseService(
                _payload(
                    status="valuation_evidence_not_ready",
                    implied_eps_cagr=None,
                )
            )
        )
    )

    assert result.status == "reverse_valuation_not_ready"
    assert result.implied_eps_cagr is None
    assert result.expectations_gap is None
    assert result.production_eligible is False
    payload = result.to_api_dict()
    assert payload["isWeightingReady"] is False
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["referenceExpectation"]["kind"] == "company_guidance"
    assert payload["referenceExpectation"]["horizonYears"] == 5


def test_expectations_gap_validates_reference_growth_range_before_upstream() -> None:
    upstream = _ReverseService(_payload())
    service = RecommendationExpectationsGapService(reverse_valuation_service=upstream)

    for value in (-1.0, 10.0001):
        with pytest.raises(ValueError, match="reference_eps_cagr"):
            _evaluate(service, reference_eps_cagr=value)
    assert upstream.calls == []
