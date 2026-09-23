from datetime import datetime, timezone

import pytest

from app.services.portfolio_dividend_return_evidence_service import (
    PortfolioDividendReturnEvidenceService,
)
from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


def _event(event_type: str, amount: float, source_ref: str) -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(
        portfolio_id="personal",
        event_type=event_type,
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        available_at=datetime(2026, 1, 16, tzinfo=UTC),
        currency="EUR",
        amount=amount,
        instrument_id="AAPL:XNAS" if event_type == "cash_dividend" else None,
        quantity=None,
        source="issuer_filing" if event_type == "cash_dividend" else "broker_statement",
        source_ref=source_ref,
    )


def test_dividend_return_evidence_keeps_gross_net_costs_and_provenance(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(as_of=AS_OF, item=_event("cash_dividend", 12.0, "aapl-div-2026q1"))
    ledger.append(as_of=AS_OF, item=_event("fee", -0.5, "custody-fee-1"))
    ledger.append(as_of=AS_OF, item=_event("tax", -2.0, "withholding-tax-1"))

    result = PortfolioDividendReturnEvidenceService(ledger).build(
        portfolio_id="personal",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )

    assert result.gross_dividends == 12.0
    assert result.fees == -0.5
    assert result.taxes == -2.0
    assert result.net_internal_cash_return == 9.5
    assert result.dividend_event_count == 1
    assert result.provenance_refs == (
        "broker_statement:custody-fee-1",
        "broker_statement:withholding-tax-1",
        "issuer_filing:aapl-div-2026q1",
    )
    payload = result.to_dict()
    assert payload["pitSafe"] is True
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_dividend_return_evidence_rejects_silent_fx(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(as_of=AS_OF, item=_event("cash_dividend", 12.0, "aapl-div-2026q1"))

    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        PortfolioDividendReturnEvidenceService(ledger).build(
            portfolio_id="personal",
            reporting_currency="USD",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )


def test_dividend_return_evidence_excludes_information_unavailable_at_cutoff(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    later_as_of = datetime(2026, 2, 10, tzinfo=UTC)
    ledger.append(
        as_of=later_as_of,
        item=PortfolioLedgerEventInput(
            portfolio_id="personal",
            event_type="cash_dividend",
            occurred_at=datetime(2026, 1, 20, tzinfo=UTC),
            available_at=datetime(2026, 2, 5, tzinfo=UTC),
            currency="EUR",
            amount=7.0,
            instrument_id="MSFT:XNAS",
            quantity=None,
            source="issuer_filing",
            source_ref="msft-late-dividend",
        ),
    )

    result = PortfolioDividendReturnEvidenceService(ledger).build(
        portfolio_id="personal",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert result.gross_dividends == 0
    assert result.dividend_event_count == 0
    assert result.provenance_refs == ()
