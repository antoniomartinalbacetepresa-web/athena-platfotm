from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
EVENT_AT = datetime(2026, 1, 10, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


def event(
    event_type: str,
    *,
    amount: float | None,
    instrument_id: str | None = None,
    quantity: float | None = None,
    currency: str = "EUR",
    source_ref: str | None = None,
) -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(
        portfolio_id="portfolio-1",
        event_type=event_type,
        occurred_at=EVENT_AT,
        available_at=EVENT_AT,
        currency=currency,
        amount=amount,
        instrument_id=instrument_id,
        quantity=quantity,
        source="broker_statement",
        source_ref=source_ref or event_type,
    )


def test_dividend_fee_and_tax_are_internal_cash_not_twr_external_flows(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(
        as_of=AS_OF,
        item=event("external_cash_flow", amount=100.0, source_ref="deposit"),
    )
    ledger.append(
        as_of=AS_OF,
        item=event(
            "cash_dividend",
            amount=5.0,
            instrument_id="FIGI:AAA",
            source_ref="dividend",
        ),
    )
    ledger.append(as_of=AS_OF, item=event("fee", amount=-1.0, source_ref="fee"))
    ledger.append(as_of=AS_OF, item=event("tax", amount=-0.5, source_ref="tax"))

    external = ledger.external_cash_flows(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    internal = ledger.internal_cash_events(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )

    assert [item.amount for item in external] == [100.0]
    assert [(item.event_type, item.amount) for item in internal] == [
        ("cash_dividend", 5.0),
        ("fee", -1.0),
        ("tax", -0.5),
    ]
    assert internal[0].instrument_id == "FIGI:AAA"


def test_typed_event_validation_is_fail_closed(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")

    invalid = (
        event("cash_dividend", amount=5.0, instrument_id=None),
        event("cash_dividend", amount=5.0, instrument_id="FIGI:AAA", quantity=1.0),
        event("fee", amount=1.0),
        event("tax", amount=0.0),
        event("split_adjustment", amount=1.0, instrument_id="FIGI:AAA", quantity=1.0),
        event("split_adjustment", amount=None, instrument_id="FIGI:AAA", quantity=0.0),
    )
    for item in invalid:
        with pytest.raises(ValueError):
            ledger.append(as_of=AS_OF, item=item)


def test_split_adjustment_is_quantity_only_and_not_cash_projection(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    record = ledger.append(
        as_of=AS_OF,
        item=event(
            "split_adjustment",
            amount=None,
            instrument_id="FIGI:AAA",
            quantity=3.0,
        ),
    )
    assert record.event.amount is None
    assert record.event.quantity == 3.0
    assert ledger.external_cash_flows(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    ) == ()
    assert ledger.internal_cash_events(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    ) == ()


def test_internal_cash_projection_requires_explicit_fx_evidence(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(
        as_of=AS_OF,
        item=event(
            "cash_dividend",
            amount=5.0,
            instrument_id="FIGI:AAA",
            currency="USD",
        ),
    )
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        ledger.internal_cash_events(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )


def test_policy_keeps_generic_corporate_action_fail_closed_and_typed_semantics_explicit(tmp_path) -> None:
    policy = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl").policy()
    typed = policy["typedEvents"]
    assert typed["cashDividend"] == "internal_cash_return_bound_to_instrument_not_external_flow"
    assert typed["fee"] == "explicit_negative_internal_cash_friction"
    assert typed["tax"] == "explicit_negative_internal_cash_friction"
    assert typed["splitAdjustment"] == "explicit_quantity_only_corporate_action"
    assert typed["corporateAction"] == "generic_form_persistable_but_state_semantics_fail_closed"
    assert policy["automaticTrading"] is False
    assert policy["productionEligible"] is False
    assert policy["isWeightingReady"] is False
