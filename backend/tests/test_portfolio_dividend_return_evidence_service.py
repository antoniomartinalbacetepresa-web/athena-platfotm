from datetime import datetime, timezone

import pytest

from app.services.portfolio_dividend_return_evidence_service import DividendFundamentalEvidence, PortfolioDividendReturnEvidenceService
from app.services.recommendation_portfolio_event_ledger_service import PortfolioLedgerEventInput, RecommendationPortfolioEventLedgerService

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


def _event(event_type: str, amount: float, source_ref: str) -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(portfolio_id="personal", event_type=event_type, occurred_at=datetime(2026, 1, 15, tzinfo=UTC), available_at=datetime(2026, 1, 16, tzinfo=UTC), currency="EUR", amount=amount, instrument_id="AAPL:XNAS" if event_type == "cash_dividend" else None, quantity=None, source="issuer_filing" if event_type == "cash_dividend" else "broker_statement", source_ref=source_ref)


def _dividend(at: datetime, source_ref: str, amount: float = 1.0, instrument_id: str = "AAPL:XNAS") -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(portfolio_id="personal", event_type="cash_dividend", occurred_at=at, available_at=at, currency="EUR", amount=amount, instrument_id=instrument_id, quantity=None, source="issuer_filing", source_ref=source_ref)


def test_dividend_return_evidence_keeps_gross_net_costs_and_provenance(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(as_of=AS_OF, item=_event("cash_dividend", 12.0, "aapl-div-2026q1"))
    ledger.append(as_of=AS_OF, item=_event("fee", -0.5, "custody-fee-1"))
    ledger.append(as_of=AS_OF, item=_event("tax", -2.0, "withholding-tax-1"))
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=START, period_end=END, as_of=AS_OF)
    assert result.gross_dividends == 12.0
    assert result.fees == -0.5
    assert result.taxes == -2.0
    assert result.net_internal_cash_return == 9.5
    assert result.dividend_event_count == 1
    assert result.observed_frequency == "insufficient_evidence"
    assert result.trailing_dividend_yield is None
    assert result.annualized_dividend_growth is None
    assert result.payment_stability is None
    assert result.sustainability == "insufficient_evidence"
    assert result.provenance_refs == ("broker_statement:custody-fee-1", "broker_statement:withholding-tax-1", "issuer_filing:aapl-div-2026q1")
    payload = result.to_dict()
    assert payload["pitSafe"] is True
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_dividend_return_evidence_classifies_observed_quarterly_cadence(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    cutoff = datetime(2026, 10, 2, tzinfo=UTC)
    for index, at in enumerate((datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 4, 15, tzinfo=UTC), datetime(2026, 7, 15, tzinfo=UTC))):
        ledger.append(as_of=cutoff, item=_dividend(at, f"quarterly-{index}"))
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=datetime(2026, 1, 1, tzinfo=UTC), period_end=datetime(2026, 10, 1, tzinfo=UTC), as_of=cutoff)
    assert result.observed_frequency == "quarterly"
    assert result.dividend_event_count == 3


def test_dividend_return_evidence_marks_mixed_cadence_irregular(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    cutoff = datetime(2026, 10, 2, tzinfo=UTC)
    for index, at in enumerate((datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 4, 15, tzinfo=UTC), datetime(2026, 5, 15, tzinfo=UTC))):
        ledger.append(as_of=cutoff, item=_dividend(at, f"irregular-{index}"))
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=datetime(2026, 1, 1, tzinfo=UTC), period_end=datetime(2026, 10, 1, tzinfo=UTC), as_of=cutoff)
    assert result.observed_frequency == "irregular"


def test_dividend_metrics_use_only_explicit_pit_fundamentals(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    cutoff = datetime(2026, 4, 2, tzinfo=UTC)
    for index, (at, amount) in enumerate(((datetime(2025, 1, 1, tzinfo=UTC), 1.0), (datetime(2026, 1, 1, tzinfo=UTC), 1.1))):
        ledger.append(as_of=cutoff, item=_dividend(at, f"growth-{index}", amount))
    fundamentals = DividendFundamentalEvidence(price=40.0, trailing_dividend_per_share=2.1, payout_ratio=0.55, fcf_payout_ratio=0.60, available_at=datetime(2026, 3, 20, tzinfo=UTC), source="issuer_filing", source_ref="aapl-2025-10k")
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=datetime(2024, 12, 31, tzinfo=UTC), period_end=datetime(2026, 4, 1, tzinfo=UTC), as_of=cutoff, fundamentals=fundamentals)
    assert result.trailing_dividend_yield == pytest.approx(2.1 / 40.0)
    assert result.annualized_dividend_growth == pytest.approx(0.10, abs=0.001)
    assert result.payment_stability > 0.95
    assert result.payout_ratio == 0.55
    assert result.fcf_payout_ratio == 0.60
    assert result.sustainability == "supported"
    assert "issuer_filing:aapl-2025-10k" in result.provenance_refs


def test_dividend_yield_never_divides_portfolio_cash_by_share_price(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(as_of=AS_OF, item=_event("cash_dividend", 1200.0, "large-position-cash"))
    fundamentals = DividendFundamentalEvidence(price=40.0, available_at=AS_OF, source="market_observation", source_ref="price-1")
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=START, period_end=END, as_of=AS_OF, fundamentals=fundamentals)
    assert result.gross_dividends == 1200.0
    assert result.trailing_dividend_yield is None


def test_dividend_fundamentals_reject_future_or_unprovenanced_evidence(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    service = PortfolioDividendReturnEvidenceService(ledger)
    future = DividendFundamentalEvidence(price=100.0, available_at=datetime(2026, 3, 1, tzinfo=UTC), source="issuer_filing", source_ref="future")
    with pytest.raises(ValueError, match="PIT-available"):
        service.build(portfolio_id="personal", reporting_currency="EUR", period_start=START, period_end=END, as_of=AS_OF, fundamentals=future)
    missing_source = DividendFundamentalEvidence(price=100.0, available_at=AS_OF)
    with pytest.raises(ValueError, match="explicit provenance"):
        service.build(portfolio_id="personal", reporting_currency="EUR", period_start=START, period_end=END, as_of=AS_OF, fundamentals=missing_source)


def test_dividend_return_evidence_rejects_silent_fx(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    ledger.append(as_of=AS_OF, item=_event("cash_dividend", 12.0, "aapl-div-2026q1"))
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="USD", period_start=START, period_end=END, as_of=AS_OF)


def test_dividend_return_evidence_excludes_information_unavailable_at_cutoff(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    later_as_of = datetime(2026, 2, 10, tzinfo=UTC)
    ledger.append(as_of=later_as_of, item=PortfolioLedgerEventInput(portfolio_id="personal", event_type="cash_dividend", occurred_at=datetime(2026, 1, 20, tzinfo=UTC), available_at=datetime(2026, 2, 5, tzinfo=UTC), currency="EUR", amount=7.0, instrument_id="MSFT:XNAS", quantity=None, source="issuer_filing", source_ref="msft-late-dividend"))
    result = PortfolioDividendReturnEvidenceService(ledger).build(portfolio_id="personal", reporting_currency="EUR", period_start=START, period_end=END, as_of=AS_OF)
    assert result.gross_dividends == 0
    assert result.dividend_event_count == 0
    assert result.observed_frequency == "insufficient_evidence"
    assert result.provenance_refs == ()



def test_portfolio_dividend_metrics_do_not_mix_instruments_into_false_cadence_or_growth(tmp_path) -> None:
    ledger = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    cutoff = datetime(2026, 5, 1, tzinfo=UTC)
    events = (
        _dividend(datetime(2025, 1, 15, tzinfo=UTC), "aapl-2025", 1.0, "AAPL:XNAS"),
        _dividend(datetime(2025, 4, 15, tzinfo=UTC), "msft-2025", 2.0, "MSFT:XNAS"),
        _dividend(datetime(2026, 1, 15, tzinfo=UTC), "aapl-2026", 1.1, "AAPL:XNAS"),
        _dividend(datetime(2026, 4, 15, tzinfo=UTC), "msft-2026", 2.2, "MSFT:XNAS"),
    )
    for item in events:
        ledger.append(as_of=cutoff, item=item)
    result = PortfolioDividendReturnEvidenceService(ledger).build(
        portfolio_id="personal",
        reporting_currency="EUR",
        period_start=datetime(2025, 1, 1, tzinfo=UTC),
        period_end=cutoff,
        as_of=cutoff,
    )
    assert result.gross_dividends == pytest.approx(6.3)
    assert result.observed_frequency == "mixed_instruments"
    assert result.annualized_dividend_growth is None
    assert result.payment_stability is None
    assert result.provenance_refs == (
        "issuer_filing:aapl-2025",
        "issuer_filing:aapl-2026",
        "issuer_filing:msft-2025",
        "issuer_filing:msft-2026",
    )
