from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_twr_ledger_binding_service import (
    PortfolioTwrExternalFlowEventInput,
    RecommendationPortfolioTwrLedgerBindingService,
)
from app.services.recommendation_portfolio_twr_measurement_service import (
    PortfolioTwrBoundaryInput,
    PortfolioTwrInternalCashEventInput,
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
    fingerprint: str,
) -> PortfolioTwrBoundaryInput:
    return PortfolioTwrBoundaryInput(
        observed_at=observed_at,
        available_at=observed_at,
        pre_flow_value=pre,
        post_flow_value=post,
        external_flow_amount=flow,
        currency="EUR",
        valuation_scope=SCOPE,
        valuation_fingerprint=fingerprint,
        source="broker_net_liquidation_statement",
        source_ref=f"valuation:{observed_at.isoformat()}",
    )


def _boundaries(*, flow_amount: float = 50.0):
    return (
        _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64),
        _boundary(FLOW, pre=110.0, post=110.0 + flow_amount, flow=flow_amount, fingerprint="2" * 64),
        _boundary(END, pre=(110.0 + flow_amount) * 1.10, post=(110.0 + flow_amount) * 1.10, fingerprint="3" * 64),
    )


def _flow(
    *,
    amount: float = 50.0,
    key: str = "a" * 64,
    source_ref: str = "deposit-1",
    occurred_at: datetime = FLOW,
    available_at: datetime = FLOW,
    currency: str = "EUR",
) -> PortfolioTwrExternalFlowEventInput:
    return PortfolioTwrExternalFlowEventInput(
        event_key=key,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        available_at=available_at,
        source="broker_statement",
        source_ref=source_ref,
    )


def _internal() -> PortfolioTwrInternalCashEventInput:
    return PortfolioTwrInternalCashEventInput(
        event_key="b" * 64,
        event_type="fee",
        amount=-1.0,
        currency="EUR",
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        available_at=datetime(2026, 1, 15, tzinfo=UTC),
        source="broker_statement",
        source_ref="fee-1",
    )


def _evaluate(*, boundaries=None, flows=None):
    return RecommendationPortfolioTwrLedgerBindingService().evaluate(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
        boundaries=boundaries if boundaries is not None else _boundaries(),
        external_cash_flows=flows if flows is not None else (_flow(),),
        internal_cash_events=(_internal(),),
    )


def test_ledger_bound_twr_reconciles_exact_external_flow_and_preserves_safety() -> None:
    result = _evaluate()

    assert result.core.time_weighted_return == pytest.approx(0.21)
    assert result.core.external_flow_total == pytest.approx(50.0)
    assert len(result.external_flow_events) == 1
    assert result.external_flow_events[0]["eventKey"] == "a" * 64
    assert len(result.measurement_key) == 64
    assert result.measurement_key != result.core.measurement_key

    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["callerMayOmitKnownExternalFlow"] is False
    assert payload["policy"]["callerMayInventExternalFlow"] is False
    assert payload["policy"]["automaticTrading"] is False


def test_known_ledger_flow_cannot_be_omitted_from_twr_boundaries() -> None:
    without_flow_boundary = (
        _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64),
        _boundary(END, pre=121.0, post=121.0, fingerprint="3" * 64),
    )

    with pytest.raises(ValueError, match="missing an exact TWR valuation boundary"):
        _evaluate(boundaries=without_flow_boundary)


def test_twr_boundary_cannot_invent_flow_absent_from_ledger() -> None:
    with pytest.raises(ValueError, match="absent from the supplied ledger evidence"):
        _evaluate(flows=())


def test_twr_boundary_flow_amount_must_match_ledger_event_exactly() -> None:
    with pytest.raises(ValueError, match="amount does not match ledger event amount"):
        _evaluate(flows=(_flow(amount=40.0),))


def test_ledger_binding_rejects_duplicate_timestamp_provenance_fx_and_lookahead() -> None:
    with pytest.raises(ValueError, match="one instant"):
        _evaluate(flows=(_flow(key="a" * 64), _flow(key="c" * 64, source_ref="deposit-2")))

    duplicate_provenance_time = datetime(2026, 1, 11, tzinfo=UTC)
    with pytest.raises(ValueError, match="duplicate provenance"):
        _evaluate(
            flows=(
                _flow(key="a" * 64, source_ref="same"),
                _flow(
                    key="c" * 64,
                    source_ref="same",
                    occurred_at=duplicate_provenance_time,
                    available_at=duplicate_provenance_time,
                ),
            )
        )

    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        _evaluate(flows=(_flow(currency="USD"),))

    with pytest.raises(ValueError, match="occurred_at <= available_at <= as_of"):
        _evaluate(flows=(_flow(available_at=datetime(2026, 1, 22, tzinfo=UTC)),))


def test_ledger_event_provenance_is_bound_into_measurement_hash() -> None:
    first = _evaluate()
    changed = _evaluate(flows=(_flow(source_ref="deposit-1-corrected-reference"),))

    assert first.core.measurement_key == changed.core.measurement_key
    assert first.measurement_key != changed.measurement_key
