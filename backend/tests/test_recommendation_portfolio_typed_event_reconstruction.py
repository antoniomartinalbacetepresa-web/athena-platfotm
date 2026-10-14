from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)
from app.services.recommendation_portfolio_state_reconstruction_service import (
    OpeningCashEvidence,
    OpeningPositionEvidence,
    RecommendationPortfolioStateReconstructionInput,
    RecommendationPortfolioStateReconstructionService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
EVENT_AT = datetime(2026, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 20, tzinfo=UTC)
AS_OF = datetime(2026, 1, 21, tzinfo=UTC)
PORTFOLIO = "portfolio-typed-events"
INSTRUMENT = "FIGI:AAA"


def _append(
    ledger: RecommendationPortfolioEventLedgerService,
    *,
    event_type: str,
    amount: float | None,
    quantity: float | None = None,
    instrument_id: str | None = None,
    currency: str = "EUR",
    source_ref: str,
) -> None:
    ledger.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id=PORTFOLIO,
            event_type=event_type,
            occurred_at=EVENT_AT,
            available_at=EVENT_AT,
            currency=currency,
            amount=amount,
            instrument_id=instrument_id,
            quantity=quantity,
            source="broker_statement",
            source_ref=source_ref,
        ),
    )


def _reconstruct(ledger: RecommendationPortfolioEventLedgerService):
    return RecommendationPortfolioStateReconstructionService(ledger).evaluate(
        as_of=AS_OF,
        item=RecommendationPortfolioStateReconstructionInput(
            portfolio_id=PORTFOLIO,
            reporting_currency="EUR",
            reconstruction_start=START,
            opening_cash=OpeningCashEvidence(
                balance=100.0,
                currency="EUR",
                observed_at=START,
                available_at=START,
                source="broker_statement",
                source_ref="opening-cash",
            ),
            opening_positions=(
                OpeningPositionEvidence(
                    instrument_id=INSTRUMENT,
                    quantity=10.0,
                    observed_at=START,
                    available_at=START,
                    source="broker_statement",
                    source_ref="opening-position",
                ),
            ),
        ),
    )


def test_typed_internal_events_reconstruct_cash_and_quantity_without_external_flow_pollution(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    _append(
        ledger,
        event_type="cash_dividend",
        amount=12.0,
        instrument_id=INSTRUMENT,
        source_ref="dividend-1",
    )
    _append(ledger, event_type="fee", amount=-2.0, source_ref="fee-1")
    _append(ledger, event_type="tax", amount=-3.0, source_ref="tax-1")
    _append(
        ledger,
        event_type="split_adjustment",
        amount=None,
        quantity=10.0,
        instrument_id=INSTRUMENT,
        source_ref="split-1",
    )

    result = _reconstruct(ledger)

    assert result.cash_balance == pytest.approx(107.0)
    assert result.positions == ({"instrumentId": INSTRUMENT, "quantity": 20.0},)
    assert len(result.applied_event_keys) == 4
    assert len(result.state_key) == 64

    external = ledger.external_cash_flows(
        portfolio_id=PORTFOLIO,
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert external == ()

    internal = ledger.internal_cash_events(
        portfolio_id=PORTFOLIO,
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert {item.event_type for item in internal} == {"cash_dividend", "fee", "tax"}
    assert sum(item.amount for item in internal) == pytest.approx(7.0)


def test_typed_internal_cash_event_requires_explicit_fx_before_reconstruction(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    _append(
        ledger,
        event_type="cash_dividend",
        amount=12.0,
        instrument_id=INSTRUMENT,
        currency="USD",
        source_ref="usd-dividend",
    )

    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        _reconstruct(ledger)


def test_generic_corporate_action_remains_fail_closed_even_after_typed_split_support(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    _append(
        ledger,
        event_type="corporate_action",
        amount=None,
        quantity=10.0,
        instrument_id=INSTRUMENT,
        source_ref="ambiguous-corporate-action",
    )

    with pytest.raises(ValueError, match="typed semantics"):
        _reconstruct(ledger)


def test_typed_fee_cannot_create_implicit_margin(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    _append(ledger, event_type="fee", amount=-150.0, source_ref="oversized-fee")

    with pytest.raises(ValueError, match="margin borrowing"):
        _reconstruct(ledger)
