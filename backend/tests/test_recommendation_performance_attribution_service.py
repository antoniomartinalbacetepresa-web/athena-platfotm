from datetime import datetime, timezone

import pytest

from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)


UTC = timezone.utc


def dt(day: int) -> datetime:
    return datetime(2026, 1, day, 12, tzinfo=UTC)


def evidence(value: float, day: int = 10) -> AttributionEvidence:
    return AttributionEvidence(
        value=value,
        available_at=dt(day),
        source="test-source",
        source_ref=f"ref-{value}",
    )


def factor(name: str, value: float, day: int = 10) -> FactorContributionEvidence:
    return FactorContributionEvidence(
        factor=name,
        contribution=value,
        available_at=dt(day),
        source="factor-source",
        source_ref=f"factor-{name}",
    )


def item(**overrides: object) -> RecommendationPerformanceAttributionInput:
    values = {
        "instrument_id": "issuer:US:0378331005",
        "symbol": "aapl",
        "instrument_currency": "usd",
        "reporting_currency": "eur",
        "fx_pair": "usd/eur",
        "benchmark_id": "benchmark:MSCI_WORLD",
        "period_start": dt(1),
        "period_end": dt(9),
        "total_return": evidence(0.12),
        "market_contribution": evidence(0.05),
        "fx_contribution": evidence(0.01),
        "factor_contributions": (factor("momentum", 0.02), factor("quality", 0.01)),
    }
    values.update(overrides)
    return RecommendationPerformanceAttributionInput(**values)


def test_arithmetic_attribution_preserves_provenance_fx_and_residual_semantics() -> None:
    result = RecommendationPerformanceAttributionService().evaluate(as_of=dt(11), item=item())
    payload = result.to_api_dict()

    assert payload["symbol"] == "AAPL"
    assert payload["benchmarkId"] == "benchmark:MSCI_WORLD"
    assert payload["currency"] == {
        "instrumentCurrency": "USD",
        "reportingCurrency": "EUR",
        "fxPair": "USD/EUR",
        "conversionRequired": True,
    }
    assert len(payload["attributionKey"]) == 64
    assert set(payload["attributionKey"]) <= set("0123456789abcdef")
    assert payload["explainedReturn"] == pytest.approx(0.09)
    assert payload["residualReturn"] == pytest.approx(0.03)
    assert payload["factorContributions"] == {"momentum": 0.02, "quality": 0.01}
    assert payload["evidence"]["factorContributions"]["momentum"]["sourceRef"] == "factor-momentum"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["causalClaim"] == "forbidden_arithmetic_attribution_only"
    assert payload["policy"]["residualInterpretation"] == "unexplained_not_automatic_stock_selection_alpha"
    assert payload["policy"]["fx"] == "explicit_currency_pair_bound_fail_closed"
    assert payload["policy"]["identity"] == "deterministic_sha256_attribution_key"


def test_attribution_key_is_deterministic_and_changes_with_evidence_identity() -> None:
    service = RecommendationPerformanceAttributionService()
    first = service.evaluate(as_of=dt(11), item=item()).attribution_key
    second = service.evaluate(as_of=dt(11), item=item()).attribution_key
    changed = service.evaluate(
        as_of=dt(11),
        item=item(
            fx_contribution=AttributionEvidence(
                value=0.01,
                available_at=dt(10),
                source="test-source",
                source_ref="different-fx-observation",
            )
        ),
    ).attribution_key
    assert first == second
    assert first != changed


def test_rejects_wrong_fx_pair() -> None:
    with pytest.raises(ValueError, match="fx_pair must be USD/EUR"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11), item=item(fx_pair="EUR/USD")
        )


def test_rejects_non_zero_fx_when_currency_conversion_is_not_required() -> None:
    with pytest.raises(ValueError, match="must be zero"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11),
            item=item(reporting_currency="USD", fx_pair="USD/USD", fx_contribution=evidence(0.01)),
        )


def test_accepts_zero_fx_when_currency_conversion_is_not_required() -> None:
    result = RecommendationPerformanceAttributionService().evaluate(
        as_of=dt(11),
        item=item(reporting_currency="USD", fx_pair="USD/USD", fx_contribution=evidence(0.0)),
    )
    assert result.fx_contribution == 0.0
    assert result.to_api_dict()["currency"]["conversionRequired"] is False


def test_rejects_invalid_currency_identity() -> None:
    with pytest.raises(ValueError, match="three-letter currency code"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11), item=item(instrument_currency="US")
        )


def test_rejects_lookahead_evidence() -> None:
    with pytest.raises(ValueError, match="not PIT"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11),
            item=item(total_return=evidence(0.12, day=12)),
        )


def test_rejects_period_end_after_as_of() -> None:
    with pytest.raises(ValueError, match="period_end cannot be after_as_of|period_end cannot be after as_of"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(8), item=item()
        )


def test_rejects_non_finite_data() -> None:
    with pytest.raises(ValueError, match="finite"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11), item=item(total_return=evidence(float("nan")))
        )


@pytest.mark.parametrize("name", ["market", "unknown_factor"])
def test_rejects_invalid_factor_identity(name: str) -> None:
    with pytest.raises(ValueError):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11), item=item(factor_contributions=(factor(name, 0.01),))
        )


def test_rejects_duplicate_factor() -> None:
    with pytest.raises(ValueError, match="duplicate factor"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11),
            item=item(factor_contributions=(factor("quality", 0.01), factor("quality", 0.02))),
        )


def test_rejects_missing_provenance() -> None:
    broken = AttributionEvidence(
        value=0.12,
        available_at=dt(10),
        source="",
        source_ref="ref",
    )
    with pytest.raises(ValueError, match="source is required"):
        RecommendationPerformanceAttributionService().evaluate(
            as_of=dt(11), item=item(total_return=broken)
        )


def test_rejects_timezone_naive_dates() -> None:
    naive = datetime(2026, 1, 11, 12)
    with pytest.raises(ValueError, match="timezone"):
        RecommendationPerformanceAttributionService().evaluate(as_of=naive, item=item())
