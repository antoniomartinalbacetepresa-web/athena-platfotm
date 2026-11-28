from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_reverse_valuation_service import (
    RecommendationReverseValuationService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _ValuationDiagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _ValuationService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _ValuationDiagnostic:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _ValuationDiagnostic(self.payload)


def _payload(
    *,
    status: str = "diagnostic_ready",
    price: float = 200.0,
    eps: float | None = 8.0,
    production_eligible: bool = False,
    as_of: datetime = AS_OF,
) -> dict[str, object]:
    return {
        "status": status,
        "symbol": "AAPL",
        "instrumentId": 7,
        "asOf": as_of.isoformat(),
        "latestPrice": price,
        "annualDilutedEps": None if eps is None else {"value": eps},
        "productionEligible": production_eligible,
    }


def test_reverse_valuation_computes_required_growth_from_explicit_assumptions() -> None:
    upstream = _ValuationService(_payload())
    result = RecommendationReverseValuationService(valuation_service=upstream).evaluate(
        symbol=" aapl ",
        as_of=AS_OF,
        horizon_years=5,
        required_return=0.10,
        exit_pe=20.0,
    )

    expected_terminal_eps = 200.0 * (1.10**5) / 20.0
    expected_cagr = (expected_terminal_eps / 8.0) ** (1.0 / 5.0) - 1.0
    assert result.status == "diagnostic_ready"
    assert result.symbol == "AAPL"
    assert result.required_terminal_eps == pytest.approx(expected_terminal_eps)
    assert result.implied_eps_cagr == pytest.approx(expected_cagr)
    assert result.production_eligible is False
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["assumptions"] == {
        "horizonYears": 5,
        "requiredReturn": 0.10,
        "exitPe": 20.0,
    }
    assert upstream.calls == [{"symbol": "AAPL", "as_of": AS_OF}]


def test_reverse_valuation_never_hides_scenario_assumptions() -> None:
    service = RecommendationReverseValuationService(
        valuation_service=_ValuationService(_payload())
    )
    with pytest.raises(TypeError):
        service.evaluate(symbol="AAPL", as_of=AS_OF, horizon_years=5)  # type: ignore[call-arg]


def test_reverse_valuation_fails_closed_on_non_finite_inputs_before_upstream_call() -> None:
    upstream = _ValuationService(_payload())
    service = RecommendationReverseValuationService(valuation_service=upstream)

    with pytest.raises(ValueError, match="finito"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=float("nan"),
            exit_pe=20.0,
        )
    with pytest.raises(ValueError, match="finito"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=0.10,
            exit_pe=float("inf"),
        )
    assert upstream.calls == []


def test_reverse_valuation_rejects_non_finite_upstream_evidence() -> None:
    service = RecommendationReverseValuationService(
        valuation_service=_ValuationService(_payload(price=float("inf")))
    )
    with pytest.raises(ValueError, match="latestPrice.*finito"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=0.10,
            exit_pe=20.0,
        )


def test_reverse_valuation_preserves_exact_pit_cutoff_and_upstream_nonproduction() -> None:
    wrong_cutoff = _ValuationService(_payload(as_of=AS_OF + timedelta(seconds=1)))
    with pytest.raises(RuntimeError, match="corte temporal"):
        RecommendationReverseValuationService(valuation_service=wrong_cutoff).evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=0.10,
            exit_pe=20.0,
        )

    productive = _ValuationService(_payload(production_eligible=True))
    with pytest.raises(RuntimeError, match="productiva"):
        RecommendationReverseValuationService(valuation_service=productive).evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=0.10,
            exit_pe=20.0,
        )


def test_reverse_valuation_returns_not_ready_without_forcing_missing_evidence() -> None:
    result = RecommendationReverseValuationService(
        valuation_service=_ValuationService(
            _payload(status="valuation_input_missing", eps=None)
        )
    ).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
        horizon_years=5,
        required_return=0.10,
        exit_pe=20.0,
    )

    assert result.status == "valuation_evidence_not_ready"
    assert result.required_terminal_eps is None
    assert result.implied_eps_cagr is None
    assert result.production_eligible is False


def test_reverse_valuation_validates_ranges_and_timezone() -> None:
    upstream = _ValuationService(_payload())
    service = RecommendationReverseValuationService(valuation_service=upstream)

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=datetime(2026, 1, 1),
            horizon_years=5,
            required_return=0.10,
            exit_pe=20.0,
        )
    with pytest.raises(ValueError, match="horizon_years"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=0,
            required_return=0.10,
            exit_pe=20.0,
        )
    with pytest.raises(ValueError, match="required_return"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=-1.0,
            exit_pe=20.0,
        )
    with pytest.raises(ValueError, match="exit_pe"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            horizon_years=5,
            required_return=0.10,
            exit_pe=0.0,
        )
    assert upstream.calls == []
