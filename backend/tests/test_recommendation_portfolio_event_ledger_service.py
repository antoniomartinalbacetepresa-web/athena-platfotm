from datetime import datetime, timezone
import json

import pytest

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW_AT = datetime(2026, 1, 16, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


def cash_flow(*, amount: float = 11.0, currency: str = "EUR", source_ref: str = "deposit-1") -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(
        portfolio_id="portfolio-1",
        event_type="external_cash_flow",
        occurred_at=FLOW_AT,
        available_at=FLOW_AT,
        currency=currency,
        amount=amount,
        instrument_id=None,
        quantity=None,
        source="broker_statement",
        source_ref=source_ref,
    )


def test_ledger_append_is_deterministic_idempotent_and_hash_chained(tmp_path) -> None:
    path = tmp_path / "portfolio-events.jsonl"
    service = RecommendationPortfolioEventLedgerService(path)

    first = service.append(as_of=AS_OF, item=cash_flow())
    repeated = service.append(as_of=AS_OF, item=cash_flow())
    second = service.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type="trade_execution",
            occurred_at=FLOW_AT,
            available_at=FLOW_AT,
            currency="EUR",
            amount=-50.0,
            instrument_id="FIGI:BBG000B9XRY4",
            quantity=2.0,
            source="broker_statement",
            source_ref="trade-1",
        ),
    )

    assert first == repeated
    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.record_hash
    assert len(first.event.event_key) == 64
    assert len(second.record_hash) == 64
    assert len(service.load()) == 2

    policy = service.policy()
    assert policy["advisoryStatus"] == "no_advice"
    assert policy["productionEligible"] is False
    assert policy["isWeightingReady"] is False
    assert policy["automaticTrading"] is False
    assert policy["orderPlacement"] == "forbidden"
    assert policy["cashInference"] == "forbidden"
    assert policy["fxInference"] == "forbidden"


def test_ledger_external_flow_projection_is_twr_ready_and_excludes_internal_trades(tmp_path) -> None:
    service = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    flow_record = service.append(as_of=AS_OF, item=cash_flow())
    service.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type="trade_execution",
            occurred_at=FLOW_AT,
            available_at=FLOW_AT,
            currency="EUR",
            amount=-50.0,
            instrument_id="FIGI:BBG000B9XRY4",
            quantity=2.0,
            source="broker_statement",
            source_ref="trade-1",
        ),
    )

    projected = service.external_cash_flows(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )

    assert len(projected) == 1
    assert projected[0].event_key == flow_record.event.event_key
    assert projected[0].amount == 11.0
    assert projected[0].source_ref == "deposit-1"


def test_ledger_rejects_late_knowledge_and_nonfinite_data(tmp_path) -> None:
    service = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    late = cash_flow()
    late = PortfolioLedgerEventInput(**{**late.__dict__, "available_at": datetime(2026, 2, 3, tzinfo=UTC)})
    with pytest.raises(ValueError, match="occurred_at <= available_at <= as_of"):
        service.append(as_of=AS_OF, item=late)

    nonfinite = PortfolioLedgerEventInput(**{**cash_flow().__dict__, "amount": float("nan")})
    with pytest.raises(ValueError, match="finite"):
        service.append(as_of=AS_OF, item=nonfinite)


def test_ledger_rejects_conflicting_duplicate_provenance(tmp_path) -> None:
    service = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    service.append(as_of=AS_OF, item=cash_flow(amount=11.0))
    with pytest.raises(ValueError, match="conflicting duplicate provenance"):
        service.append(as_of=AS_OF, item=cash_flow(amount=12.0))


def test_ledger_requires_explicit_fx_evidence_instead_of_silent_conversion(tmp_path) -> None:
    service = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    service.append(as_of=AS_OF, item=cash_flow(currency="USD"))
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        service.external_cash_flows(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )


def test_ledger_detects_tampering_on_reload(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    service = RecommendationPortfolioEventLedgerService(path)
    service.append(as_of=AS_OF, item=cash_flow())

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["event"]["amount"] = 999.0
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="record hash is invalid"):
        service.load()


def test_ledger_rejects_order_like_or_underspecified_events(tmp_path) -> None:
    service = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError, match="unsupported"):
        service.append(
            as_of=AS_OF,
            item=PortfolioLedgerEventInput(
                portfolio_id="portfolio-1",
                event_type="order",
                occurred_at=FLOW_AT,
                available_at=FLOW_AT,
                currency="EUR",
                amount=10.0,
                instrument_id="FIGI:X",
                quantity=1.0,
                source="ui",
                source_ref="order-1",
            ),
        )
    with pytest.raises(ValueError, match="trade_execution requires"):
        service.append(
            as_of=AS_OF,
            item=PortfolioLedgerEventInput(
                portfolio_id="portfolio-1",
                event_type="trade_execution",
                occurred_at=FLOW_AT,
                available_at=FLOW_AT,
                currency="EUR",
                amount=None,
                instrument_id="FIGI:X",
                quantity=1.0,
                source="broker_statement",
                source_ref="trade-2",
            ),
        )
