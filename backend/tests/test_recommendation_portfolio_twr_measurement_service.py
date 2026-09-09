from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_twr_measurement_service import (
    PortfolioTwrBoundaryInput,
    PortfolioTwrInternalCashEventInput,
    RecommendationPortfolioTwrMeasurementService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW = datetime(2026, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 20, tzinfo=UTC)
AS_OF = datetime(2026, 1, 21, tzinfo=UTC)
SCOPE = "total_net_liquidation_value_in_reporting_currency"


def _boundary(
    observed_at: datetime,
    *,
    pre: float,
    post: float,
    flow: float = 0.0,
    currency: str = "EUR",
    scope: str = SCOPE,
    fingerprint: str = "a" * 64,
    source_ref: str = "valuation:1",
    available_at: datetime | None = None,
) -> PortfolioTwrBoundaryInput:
    return PortfolioTwrBoundaryInput(
        observed_at=observed_at,
        available_at=available_at or observed_at,
        pre_flow_value=pre,
        post_flow_value=post,
        external_flow_amount=flow,
        currency=currency,
        valuation_scope=scope,
        valuation_fingerprint=fingerprint,
        source="broker_net_liquidation_statement",
        source_ref=source_ref,
    )


def _event(
    event_type: str,
    amount: float,
    *,
    key: str,
    source_ref: str,
    currency: str = "EUR",
) -> PortfolioTwrInternalCashEventInput:
    return PortfolioTwrInternalCashEventInput(
        event_key=key,
        event_type=event_type,
        amount=amount,
        currency=currency,
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        available_at=datetime(2026, 1, 15, tzinfo=UTC),
        source="broker_statement",
        source_ref=source_ref,
    )


def _measure(*, boundaries=None, events=()):
    return RecommendationPortfolioTwrMeasurementService().evaluate(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
        boundaries=boundaries
        or (
            _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64, source_ref="start"),
            _boundary(FLOW, pre=110.0, post=160.0, flow=50.0, fingerprint="2" * 64, source_ref="flow"),
            _boundary(END, pre=176.0, post=176.0, fingerprint="3" * 64, source_ref="end"),
        ),
        internal_cash_events=events,
    )


def test_twr_links_subperiod_returns_and_excludes_external_contribution() -> None:
    result = _measure(
        events=(
            _event("cash_dividend", 4.0, key="4" * 64, source_ref="dividend"),
            _event("fee", -1.0, key="5" * 64, source_ref="fee"),
            _event("tax", -0.5, key="6" * 64, source_ref="tax"),
        )
    )

    assert result.time_weighted_return == pytest.approx(0.21)
    assert [item["return"] for item in result.segment_returns] == pytest.approx([0.10, 0.10])
    assert result.external_flow_total == pytest.approx(50.0)
    assert result.internal_cash_totals == {
        "cash_dividend": pytest.approx(4.0),
        "fee": pytest.approx(-1.0),
        "tax": pytest.approx(-0.5),
    }
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["causalAttribution"] == (
        "not_estimated_from_monetary_events_without_valid_return_denominator"
    )
    assert len(result.measurement_key) == 64


def test_twr_is_deterministic_and_provenance_changes_measurement_key() -> None:
    first = _measure()
    second = _measure()
    changed = _measure(
        boundaries=(
            _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64, source_ref="start:v2"),
            _boundary(FLOW, pre=110.0, post=160.0, flow=50.0, fingerprint="2" * 64, source_ref="flow"),
            _boundary(END, pre=176.0, post=176.0, fingerprint="3" * 64, source_ref="end"),
        )
    )

    assert first.measurement_key == second.measurement_key
    assert changed.time_weighted_return == pytest.approx(first.time_weighted_return)
    assert changed.measurement_key != first.measurement_key


def test_twr_rejects_unreconciled_external_flow_and_partial_valuation_scope() -> None:
    with pytest.raises(ValueError, match="does not reconcile"):
        _measure(
            boundaries=(
                _boundary(START, pre=100.0, post=100.0),
                _boundary(FLOW, pre=110.0, post=150.0, flow=50.0, fingerprint="2" * 64),
                _boundary(END, pre=165.0, post=165.0, fingerprint="3" * 64),
            )
        )

    with pytest.raises(ValueError, match="partial position valuation is insufficient"):
        _measure(
            boundaries=(
                _boundary(
                    START,
                    pre=100.0,
                    post=100.0,
                    scope="invested_long_positions_only_cash_liabilities_unsettled_excluded",
                ),
                _boundary(END, pre=110.0, post=110.0, fingerprint="3" * 64),
            )
        )


def test_twr_rejects_missing_exact_flow_boundary_and_invalid_period_edges() -> None:
    # A caller cannot encode a mid-period contribution without an explicit boundary.
    # With only start/end, TWR is mathematically the simple total-value return.
    simple = _measure(
        boundaries=(
            _boundary(START, pre=100.0, post=100.0),
            _boundary(END, pre=121.0, post=121.0, fingerprint="3" * 64),
        )
    )
    assert simple.time_weighted_return == pytest.approx(0.21)
    assert simple.external_flow_total == 0.0

    with pytest.raises(ValueError, match="start/end TWR boundaries cannot carry external flows"):
        _measure(
            boundaries=(
                _boundary(START, pre=100.0, post=110.0, flow=10.0),
                _boundary(END, pre=121.0, post=121.0, fingerprint="3" * 64),
            )
        )


def test_twr_rejects_fx_inference_lookahead_naive_and_nonfinite_values() -> None:
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        _measure(
            boundaries=(
                _boundary(START, pre=100.0, post=100.0, currency="USD"),
                _boundary(END, pre=110.0, post=110.0, fingerprint="3" * 64),
            )
        )

    with pytest.raises(ValueError, match="observed_at <= available_at <= as_of"):
        _measure(
            boundaries=(
                _boundary(START, pre=100.0, post=100.0, available_at=datetime(2026, 1, 22, tzinfo=UTC)),
                _boundary(END, pre=110.0, post=110.0, fingerprint="3" * 64),
            )
        )

    with pytest.raises(ValueError, match="must include timezone"):
        RecommendationPortfolioTwrMeasurementService().evaluate(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=datetime(2026, 1, 1),
            period_end=END,
            as_of=AS_OF,
            boundaries=(),
        )

    with pytest.raises(ValueError, match="must be finite"):
        _measure(
            boundaries=(
                _boundary(START, pre=float("nan"), post=100.0),
                _boundary(END, pre=110.0, post=110.0, fingerprint="3" * 64),
            )
        )


def test_twr_rejects_bad_internal_cash_event_semantics_and_duplicates() -> None:
    with pytest.raises(ValueError, match="fee amount must be negative"):
        _measure(events=(_event("fee", 1.0, key="4" * 64, source_ref="fee"),))

    duplicated = _event("tax", -1.0, key="5" * 64, source_ref="tax")
    with pytest.raises(ValueError, match="duplicate event_key"):
        _measure(events=(duplicated, duplicated))

    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        _measure(
            events=(
                _event("cash_dividend", 2.0, key="6" * 64, source_ref="usd-dividend", currency="USD"),
            )
        )
