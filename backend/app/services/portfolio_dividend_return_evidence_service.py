from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from statistics import mean, median, pstdev

from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
)


@dataclass(frozen=True)
class DividendFundamentalEvidence:
    """Optional PIT fundamentals supplied by a provenance-bound upstream observation."""

    price: float | None = None
    trailing_dividend_per_share: float | None = None
    payout_ratio: float | None = None
    fcf_payout_ratio: float | None = None
    available_at: datetime | None = None
    source: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class PortfolioDividendReturnEvidence:
    currency: str
    gross_dividends: float
    fees: float
    taxes: float
    net_internal_cash_return: float
    dividend_event_count: int
    observed_frequency: str
    trailing_dividend_per_share: float | None
    trailing_dividend_yield: float | None
    annualized_dividend_growth: float | None
    payment_stability: float | None
    payout_ratio: float | None
    fcf_payout_ratio: float | None
    sustainability: str
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
            "trailingDividendPerShare": self.trailing_dividend_per_share,
            "trailingDividendYield": self.trailing_dividend_yield,
            "annualizedDividendGrowth": self.annualized_dividend_growth,
            "paymentStability": self.payment_stability,
            "payoutRatio": self.payout_ratio,
            "fcfPayoutRatio": self.fcf_payout_ratio,
            "sustainability": self.sustainability,
            "provenanceRefs": list(self.provenance_refs),
            "pitSafe": True,
            "productionEligible": False,
            "automaticTrading": False,
        }


class PortfolioDividendReturnEvidenceService:
    """Aggregate observed dividend return without inventing FX, fundamentals or future payouts."""

    def __init__(self, ledger: RecommendationPortfolioEventLedgerService):
        self._ledger = ledger

    @staticmethod
    def _observed_frequency(dividends) -> str:
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

    @staticmethod
    def _single_instrument(dividends) -> bool:
        """Return True only when observed dividend events belong to one instrument."""
        instruments = {item.instrument_id for item in dividends if item.instrument_id}
        return len(instruments) <= 1

    @staticmethod
    def _stability(dividends) -> float | None:
        amounts = [item.amount for item in dividends if item.amount > 0]
        if len(amounts) < 2:
            return None
        average = mean(amounts)
        if average <= 0:
            return None
        return max(0.0, min(1.0, 1.0 - pstdev(amounts) / average))

    @staticmethod
    def _annualized_growth(dividends) -> float | None:
        ordered = sorted((item for item in dividends if item.amount > 0), key=lambda item: item.occurred_at)
        if len(ordered) < 2 or ordered[0].amount <= 0:
            return None
        years = (ordered[-1].occurred_at - ordered[0].occurred_at).total_seconds() / (365.25 * 86400.0)
        if years < 0.75:
            return None
        return (ordered[-1].amount / ordered[0].amount) ** (1.0 / years) - 1.0

    @staticmethod
    def _fundamentals(evidence: DividendFundamentalEvidence | None, *, as_of: datetime) -> tuple[float | None, float | None, float | None, float | None, str, tuple[str, ...]]:
        if evidence is None:
            return None, None, None, None, "insufficient_evidence", ()
        if evidence.available_at is None or evidence.available_at.tzinfo is None or evidence.available_at > as_of:
            raise ValueError("dividend fundamentals must be PIT-available at as_of")
        if not evidence.source or not evidence.source_ref:
            raise ValueError("dividend fundamentals require explicit provenance")
        values = (evidence.price, evidence.trailing_dividend_per_share, evidence.payout_ratio, evidence.fcf_payout_ratio)
        try:
            finite = all(value is None or math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("dividend fundamentals must be numeric and finite") from exc
        if not finite:
            raise ValueError("dividend fundamentals must be numeric and finite")
        if evidence.price is not None and evidence.price <= 0:
            raise ValueError("dividend fundamental price must be positive")
        if evidence.trailing_dividend_per_share is not None and evidence.trailing_dividend_per_share < 0:
            raise ValueError("trailing dividend per share cannot be negative")
        payout = None if evidence.payout_ratio is None else float(evidence.payout_ratio)
        fcf = None if evidence.fcf_payout_ratio is None else float(evidence.fcf_payout_ratio)
        available_ratios = [ratio for ratio in (payout, fcf) if ratio is not None]
        if not available_ratios:
            sustainability = "insufficient_evidence"
        elif any(ratio < 0 or ratio > 1.0 for ratio in available_ratios):
            sustainability = "stressed"
        elif all(ratio <= 0.75 for ratio in available_ratios):
            sustainability = "supported"
        else:
            sustainability = "watch"
        price = None if evidence.price is None else float(evidence.price)
        trailing_dps = None if evidence.trailing_dividend_per_share is None else float(evidence.trailing_dividend_per_share)
        return price, trailing_dps, payout, fcf, sustainability, (f"{evidence.source}:{evidence.source_ref}",)

    def build(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
        fundamentals: DividendFundamentalEvidence | None = None,
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
        price, trailing_dps, payout, fcf, sustainability, fundamental_refs = self._fundamentals(fundamentals, as_of=as_of)
        # Ledger dividend amounts are portfolio cash totals, not per-share distributions.
        # Dividing those totals by a share price is dimensionally wrong and varies with
        # position size. Yield therefore requires explicit PIT trailing DPS evidence.
        trailing_yield = None if price is None or trailing_dps is None else trailing_dps / price
        refs = tuple(sorted({f"{item.source}:{item.source_ref}" for item in events}.union(fundamental_refs)))
        return PortfolioDividendReturnEvidence(
            currency=reporting_currency.strip().upper(),
            gross_dividends=gross_dividends,
            fees=fee_total,
            taxes=tax_total,
            net_internal_cash_return=gross_dividends + fee_total + tax_total,
            dividend_event_count=len(dividends),
            # Cadence/growth/stability are per-security concepts. Combining cash
            # distributions from different instruments can manufacture a plausible
            # cadence or growth rate that no holding actually has.
            observed_frequency=(self._observed_frequency(dividends) if self._single_instrument(dividends) else "mixed_instruments"),
            trailing_dividend_per_share=trailing_dps,
            trailing_dividend_yield=trailing_yield,
            annualized_dividend_growth=(self._annualized_growth(dividends) if self._single_instrument(dividends) else None),
            payment_stability=(self._stability(dividends) if self._single_instrument(dividends) else None),
            payout_ratio=payout,
            fcf_payout_ratio=fcf,
            sustainability=sustainability,
            provenance_refs=refs,
        )
