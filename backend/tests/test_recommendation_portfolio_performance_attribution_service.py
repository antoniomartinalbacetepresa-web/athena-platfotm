from datetime import datetime, timezone

import pytest

from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
)
from app.services.recommendation_portfolio_performance_attribution_service import (
    PortfolioAttributionConstituent,
    RecommendationPortfolioPerformanceAttributionInput,
    RecommendationPortfolioPerformanceAttributionService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)


def evidence(value: float, *, available_at: datetime, ref: str) -> AttributionEvidence:
    return AttributionEvidence(
        value=value,
        available_at=available_at,
        source="athena_test",
        source_ref=ref,
    )


def attribution(
    instrument_id: str,
    symbol: str,
    *,
    total: float,
    market: float,
    fx: float,
    instrument_currency: str = "USD",
) -> RecommendationPerformanceAttributionInput:
    return RecommendationPerformanceAttributionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        instrument_currency=instrument_currency,
        reporting_currency="USD",
        fx_pair=f"{instrument_currency}/USD",
        benchmark_id="SP500_TR",
        period_start=START,
        period_end=END,
        total_return=evidence(total, available_at=END, ref=f"{instrument_id}:total"),
        market_contribution=evidence(market, available_at=END, ref=f"{instrument_id}:market"),
        fx_contribution=evidence(fx, available_at=END, ref=f"{instrument_id}:fx"),
        factor_contributions=(
            FactorContributionEvidence(
                factor="quality",
                contribution=0.01,
                available_at=END,
                source="athena_test",
                source_ref=f"{instrument_id}:quality",
            ),
        ),
    )


def item(*, second_benchmark: str | None = None) -> RecommendationPortfolioPerformanceAttributionInput:
    second = attribution("inst-b", "BBB", total=-0.02, market=-0.01, fx=0.0)
    if second_benchmark is not None:
        second = RecommendationPerformanceAttributionInput(
            **{**second.__dict__, "benchmark_id": second_benchmark}
        )
    return RecommendationPortfolioPerformanceAttributionInput(
        portfolio_id="portfolio-1",
        benchmark_id="SP500_TR",
        reporting_currency="USD",
        period_start=START,
        period_end=END,
        observed_portfolio_return=evidence(0.032, available_at=END, ref="portfolio:return"),
        constituents=(
            PortfolioAttributionConstituent(
                weight=evidence(0.6, available_at=START, ref="weight:a"),
                attribution=attribution("inst-a", "AAA", total=0.08, market=0.04, fx=0.0),
            ),
            PortfolioAttributionConstituent(
                weight=evidence(0.4, available_at=START, ref="weight:b"),
                attribution=second,
            ),
        ),
    )


def test_reconciles_portfolio_and_preserves_safe_contract() -> None:
    result = RecommendationPortfolioPerformanceAttributionService().evaluate(
        as_of=AS_OF,
        item=item(),
    )
    payload = result.to_api_dict()

    assert result.reconstructed_portfolio_return == pytest.approx(0.032)
    assert result.reconciliation_error == pytest.approx(0.0)
    assert result.market_contribution == pytest.approx(0.02)
    assert result.fx_contribution == pytest.approx(0.0)
    assert result.factor_contributions["quality"] == pytest.approx(0.01)
    assert result.explained_return == pytest.approx(0.03)
    assert result.residual_return == pytest.approx(0.002)
    assert len(result.portfolio_attribution_key) == 64
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["residualInterpretation"] == "unexplained_not_automatic_stock_selection_alpha"


def test_rejects_weight_known_after_period_start() -> None:
    base = item()
    late = PortfolioAttributionConstituent(
        weight=evidence(
            0.6,
            available_at=datetime(2026, 8, 2, tzinfo=UTC),
            ref="late-weight",
        ),
        attribution=base.constituents[0].attribution,
    )
    changed = RecommendationPortfolioPerformanceAttributionInput(
        **{**base.__dict__, "constituents": (late, base.constituents[1])}
    )
    with pytest.raises(ValueError, match="not PIT"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(as_of=AS_OF, item=changed)


def test_rejects_weights_that_do_not_sum_to_one() -> None:
    base = item()
    changed_second = PortfolioAttributionConstituent(
        weight=evidence(0.3, available_at=START, ref="weight:b:bad"),
        attribution=base.constituents[1].attribution,
    )
    changed = RecommendationPortfolioPerformanceAttributionInput(
        **{**base.__dict__, "constituents": (base.constituents[0], changed_second)}
    )
    with pytest.raises(ValueError, match="sum to 1.0"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(as_of=AS_OF, item=changed)


def test_rejects_observed_return_that_does_not_reconcile() -> None:
    base = item()
    changed = RecommendationPortfolioPerformanceAttributionInput(
        **{
            **base.__dict__,
            "observed_portfolio_return": evidence(0.05, available_at=END, ref="bad-return"),
        }
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(as_of=AS_OF, item=changed)


def test_rejects_mixed_benchmarks() -> None:
    with pytest.raises(ValueError, match="benchmark_id"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(
            as_of=AS_OF,
            item=item(second_benchmark="OTHER"),
        )


def test_rejects_duplicate_instrument_identity() -> None:
    base = item()
    duplicate = PortfolioAttributionConstituent(
        weight=evidence(0.4, available_at=START, ref="weight:duplicate"),
        attribution=attribution("inst-a", "AAA", total=-0.02, market=-0.01, fx=0.0),
    )
    changed = RecommendationPortfolioPerformanceAttributionInput(
        **{**base.__dict__, "constituents": (base.constituents[0], duplicate)}
    )
    with pytest.raises(ValueError, match="duplicate instrument_id"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(as_of=AS_OF, item=changed)


def test_portfolio_key_is_order_independent() -> None:
    service = RecommendationPortfolioPerformanceAttributionService()
    base = item()
    forward = service.evaluate(as_of=AS_OF, item=base)
    reversed_item = RecommendationPortfolioPerformanceAttributionInput(
        **{**base.__dict__, "constituents": tuple(reversed(base.constituents))}
    )
    reverse = service.evaluate(as_of=AS_OF, item=reversed_item)
    assert forward.portfolio_attribution_key == reverse.portfolio_attribution_key


def test_rejects_nonfinite_weight() -> None:
    base = item()
    bad = PortfolioAttributionConstituent(
        weight=evidence(float("nan"), available_at=START, ref="weight:nan"),
        attribution=base.constituents[0].attribution,
    )
    changed = RecommendationPortfolioPerformanceAttributionInput(
        **{**base.__dict__, "constituents": (bad, base.constituents[1])}
    )
    with pytest.raises(ValueError, match="finite"):
        RecommendationPortfolioPerformanceAttributionService().evaluate(as_of=AS_OF, item=changed)
