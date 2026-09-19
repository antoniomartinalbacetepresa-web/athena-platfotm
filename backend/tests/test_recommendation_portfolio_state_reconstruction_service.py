from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.portfolio_owner_storage import owner_scoped_ledger_path
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
FLOW_AT = datetime(2026, 1, 10, tzinfo=UTC)
TRADE_AT = datetime(2026, 1, 11, tzinfo=UTC)
AS_OF = datetime(2026, 1, 20, tzinfo=UTC)
_TEST_OWNER = 101


def opening_cash(*, available_at: datetime = START, currency: str = "EUR") -> OpeningCashEvidence:
    return OpeningCashEvidence(
        balance=100.0,
        currency=currency,
        observed_at=START,
        available_at=available_at,
        source="broker_statement",
        source_ref="opening-cash",
    )


def opening_position(
    instrument_id: str = "FIGI:AAA",
    *,
    quantity: float = 1.0,
    source_ref: str = "opening-position",
) -> OpeningPositionEvidence:
    return OpeningPositionEvidence(
        instrument_id=instrument_id,
        quantity=quantity,
        observed_at=START,
        available_at=START,
        source="broker_statement",
        source_ref=source_ref,
    )


def append_event(
    ledger: RecommendationPortfolioEventLedgerService,
    *,
    event_type: str,
    occurred_at: datetime,
    amount: float | None,
    instrument_id: str | None = None,
    quantity: float | None = None,
    currency: str = "EUR",
    source_ref: str,
) -> None:
    ledger.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type=event_type,
            occurred_at=occurred_at,
            available_at=occurred_at,
            currency=currency,
            amount=amount,
            instrument_id=instrument_id,
            quantity=quantity,
            source="broker_statement",
            source_ref=source_ref,
        ),
    )


def evaluate(
    ledger: RecommendationPortfolioEventLedgerService,
    *,
    opening_positions: tuple[OpeningPositionEvidence, ...] = (),
    cash: OpeningCashEvidence | None = None,
):
    service = RecommendationPortfolioStateReconstructionService(ledger)
    return service.evaluate(
        as_of=AS_OF,
        item=RecommendationPortfolioStateReconstructionInput(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            reconstruction_start=START,
            opening_cash=cash or opening_cash(),
            opening_positions=opening_positions,
        ),
    )


def test_reconstruction_applies_external_flows_and_trade_executions(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    append_event(
        ledger,
        event_type="external_cash_flow",
        occurred_at=FLOW_AT,
        amount=50.0,
        source_ref="deposit-1",
    )
    append_event(
        ledger,
        event_type="trade_execution",
        occurred_at=TRADE_AT,
        amount=-40.0,
        instrument_id="FIGI:AAA",
        quantity=2.0,
        source_ref="trade-1",
    )

    result = evaluate(ledger, opening_positions=(opening_position(),))

    assert result.cash_balance == pytest.approx(110.0)
    assert result.positions == ({"instrumentId": "FIGI:AAA", "quantity": 3.0},)
    assert len(result.applied_event_keys) == 2
    assert len(result.state_key) == 64
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["cashInference"] == "forbidden"
    assert payload["policy"]["fxInference"] == "forbidden"


def test_reconstruction_is_deterministic_independent_of_opening_position_order(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    first = evaluate(
        ledger,
        opening_positions=(
            opening_position("FIGI:BBB", quantity=2.0, source_ref="b"),
            opening_position("FIGI:AAA", quantity=1.0, source_ref="a"),
        ),
    )
    second = evaluate(
        ledger,
        opening_positions=(
            opening_position("FIGI:AAA", quantity=1.0, source_ref="a"),
            opening_position("FIGI:BBB", quantity=2.0, source_ref="b"),
        ),
    )

    assert first.positions == second.positions
    assert first.state_key == second.state_key


def test_reconstruction_rejects_late_opening_evidence_and_duplicate_identity(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    late = opening_cash(available_at=datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="opening cash violates"):
        evaluate(ledger, cash=late)

    duplicate = (
        opening_position("FIGI:AAA", source_ref="a"),
        opening_position("FIGI:AAA", source_ref="b"),
    )
    with pytest.raises(ValueError, match="duplicate instrument identity"):
        evaluate(ledger, opening_positions=duplicate)


def test_reconstruction_requires_explicit_fx_and_typed_corporate_actions(tmp_path) -> None:
    fx_ledger = RecommendationPortfolioEventLedgerService(tmp_path / "fx.jsonl")
    append_event(
        fx_ledger,
        event_type="external_cash_flow",
        occurred_at=FLOW_AT,
        amount=10.0,
        currency="USD",
        source_ref="usd-flow",
    )
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        evaluate(fx_ledger)

    ca_ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ca.jsonl")
    append_event(
        ca_ledger,
        event_type="corporate_action",
        occurred_at=FLOW_AT,
        amount=None,
        instrument_id="FIGI:AAA",
        quantity=1.0,
        source_ref="split-ambiguous",
    )
    with pytest.raises(ValueError, match="typed semantics"):
        evaluate(ca_ledger, opening_positions=(opening_position(),))


def test_reconstruction_fails_closed_on_margin_or_short_state(tmp_path) -> None:
    margin_ledger = RecommendationPortfolioEventLedgerService(tmp_path / "margin.jsonl")
    append_event(
        margin_ledger,
        event_type="trade_execution",
        occurred_at=TRADE_AT,
        amount=-150.0,
        instrument_id="FIGI:AAA",
        quantity=1.0,
        source_ref="overbuy",
    )
    with pytest.raises(ValueError, match="margin borrowing"):
        evaluate(margin_ledger)

    short_ledger = RecommendationPortfolioEventLedgerService(tmp_path / "short.jsonl")
    append_event(
        short_ledger,
        event_type="trade_execution",
        occurred_at=TRADE_AT,
        amount=50.0,
        instrument_id="FIGI:AAA",
        quantity=-2.0,
        source_ref="oversell",
    )
    with pytest.raises(ValueError, match="short position"):
        evaluate(short_ledger, opening_positions=(opening_position(),))


def test_reconstruction_api_is_registered_and_preserves_safety_contract(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = RecommendationPortfolioEventLedgerService(
        owner_scoped_ledger_path(path, owner_user_id=_TEST_OWNER)
    )
    append_event(
        ledger,
        event_type="trade_execution",
        occurred_at=TRADE_AT,
        amount=-40.0,
        instrument_id="FIGI:AAA",
        quantity=2.0,
        source_ref="api-trade",
    )
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(path))
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-state-reconstruction",
        json={
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "reconstructionStart": START.isoformat(),
            "openingCash": {
                "balance": 100.0,
                "currency": "EUR",
                "observedAt": START.isoformat(),
                "availableAt": START.isoformat(),
                "source": "broker_statement",
                "sourceRef": "opening-cash",
            },
            "openingPositions": [],
            "asOf": AS_OF.isoformat(),
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cashBalance"] == pytest.approx(60.0)
    assert data["positions"] == [{"instrumentId": "FIGI:AAA", "quantity": 2.0}]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False


def test_reconstruction_api_rejects_naive_as_of_without_turning_it_into_500(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(path))
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-state-reconstruction",
        json={
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "reconstructionStart": START.isoformat(),
            "openingCash": {
                "balance": 100.0,
                "currency": "EUR",
                "observedAt": START.isoformat(),
                "availableAt": START.isoformat(),
                "source": "broker_statement",
                "sourceRef": "opening-cash",
            },
            "openingPositions": [],
            "asOf": "2026-01-20T00:00:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
