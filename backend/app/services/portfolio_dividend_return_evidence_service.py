from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
)


@dataclass(frozen=True)
class PortfolioDividendReturnEvidence:
    currency: str
    gross_dividends: float
    fees: float
    taxes: float
    net_internal_cash_return: float
    dividend_event_count: int
    provenance_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "grossDividends": self.gross_dividends,
            "fees": self.fees,
            "taxes": self.taxes,
            "netInternalCashReturn": self.net_internal_cash_return,
            "dividendEventCount": self.dividend_event_count,
            "provenanceRefs": list(self.provenance_refs),
            "pitSafe": True,
            "productionEligible": False,
            "automaticTrading": False,
        }


class PortfolioDividendReturnEvidenceService:
    """Aggregate observed dividend cash return without inventing FX or missing evidence."""

    def __init__(self, ledger: RecommendationPortfolioEventLedgerService):
        self._ledger = ledger

    def build(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> PortfolioDividendReturnEvidence:
        events = self._ledger.internal_cash_events(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        dividends = tuple(item for item in events if item.event_type == "cash_dividend")
        fees = tuple(item for item in events if item.event_type == "fee")
        taxes = tuple(item for item in events if item.event_type == "tax")
        gross_dividends = sum(item.amount for item in dividends)
        fee_total = sum(item.amount for item in fees)
        tax_total = sum(item.amount for item in taxes)
        refs = tuple(sorted({f"{item.source}:{item.source_ref}" for item in events}))
        return PortfolioDividendReturnEvidence(
            currency=reporting_currency.strip().upper(),
            gross_dividends=gross_dividends,
            fees=fee_total,
            taxes=tax_total,
            net_internal_cash_return=gross_dividends + fee_total + tax_total,
            dividend_event_count=len(dividends),
            provenance_refs=refs,
        )
