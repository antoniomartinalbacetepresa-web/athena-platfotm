from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

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
    observed_frequency: str
    provenance_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "grossDividends": self.gross_dividends,
            "fees": self.fees,
            "taxes": self.taxes,
            "netInternalCashReturn": self.net_internal_cash_return,
            "dividendEventCount": self.dividend_event_count,
            "observedFrequency": self.observed_frequency,
            "provenanceRefs": list(self.provenance_refs),
            "pitSafe": True,
            "productionEligible": False,
            "automaticTrading": False,
        }


class PortfolioDividendReturnEvidenceService:
    """Aggregate observed dividend cash return without inventing FX or missing evidence."""

    def __init__(self, ledger: RecommendationPortfolioEventLedgerService):
        self._ledger = ledger

    @staticmethod
    def _observed_frequency(dividends) -> str:
        """Classify cadence from observed dates only; never infer a promised schedule."""
        dates = sorted(item.occurred_at for item in dividends)
        if len(dates) < 2:
            return "insufficient_evidence"
        gaps = [(right - left).total_seconds() / 86400.0 for left, right in zip(dates, dates[1:])]
        typical_gap = median(gaps)
        if 20 <= typical_gap <= 40:
            candidate = "monthly"
        elif 70 <= typical_gap <= 110:
            candidate = "quarterly"
        elif 150 <= typical_gap <= 220:
            candidate = "semiannual"
        elif 300 <= typical_gap <= 430:
            candidate = "annual"
        else:
            return "irregular"
        lower, upper = {
            "monthly": (20, 40),
            "quarterly": (70, 110),
            "semiannual": (150, 220),
            "annual": (300, 430),
        }[candidate]
        return candidate if all(lower <= gap <= upper for gap in gaps) else "irregular"

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
            observed_frequency=self._observed_frequency(dividends),
            provenance_refs=refs,
        )
