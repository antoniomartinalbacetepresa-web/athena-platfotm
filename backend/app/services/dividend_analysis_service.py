from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository


@dataclass(frozen=True)
class DividendAnalysis:
    payment_count: int
    annualized_cash_per_share: float | None
    trailing_cash_per_share: float
    trailing_yield: float | None
    cash_per_share_60d: float | None
    yield_60d: float | None
    frequency: str
    payments_per_year: float | None
    regularity_score: float | None
    dividend_growth_rate: float | None
    cut_detected: bool | None
    consecutive_full_years_without_cut: int | None
    payment_stability_score: float | None
    suspected_suspension: bool | None
    currency: str | None
    currency_consistent: bool
    knowledge_cutoff: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "paymentCount": self.payment_count,
            "annualizedCashPerShare": self.annualized_cash_per_share,
            "trailingCashPerShare": self.trailing_cash_per_share,
            "trailingYield": self.trailing_yield,
            "cashPerShare60d": self.cash_per_share_60d,
            "yield60d": self.yield_60d,
            "frequency": self.frequency,
            "paymentsPerYear": self.payments_per_year,
            "regularityScore": self.regularity_score,
            "dividendGrowthRate": self.dividend_growth_rate,
            "cutDetected": self.cut_detected,
            "consecutiveFullYearsWithoutCut": self.consecutive_full_years_without_cut,
            "paymentStabilityScore": self.payment_stability_score,
            "suspectedSuspension": self.suspected_suspension,
            "currency": self.currency,
            "currencyConsistent": self.currency_consistent,
            "knowledgeCutoff": self.knowledge_cutoff,
            "pitSafe": True,
        }


class DividendAnalysisService:
    """PIT-safe dividend cadence, growth and cash-distribution diagnostics.

    This service intentionally does not turn dividend yield into a recommendation.
    It supplies evidence for total-return/recommendation engines. Duplicate economic
    events learned from multiple providers are collapsed before cadence is measured.
    Growth compares adjacent 365-day PIT windows and is omitted when the prior window
    has no comparable cash evidence. No-cut years are counted only across consecutive
    fully observable annual comparisons inside the requested lookback. A suspected
    suspension requires at least three sufficiently regular observed intervals.
    """

    _MIN_SUSPENSION_INTERVALS = 3
    _MIN_SUSPENSION_REGULARITY = 0.80
    _SUSPENSION_OVERDUE_MULTIPLIER = 1.75

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)

    def analyze(self, *, instrument_id: int, knowledge_cutoff: datetime, lookback_days: int = 730, pit_price: float | None = None) -> DividendAnalysis:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")
        if lookback_days < 365:
            raise ValueError("lookback_days debe ser al menos 365 para inferir frecuencia.")
        if pit_price is not None and pit_price <= 0:
            raise ValueError("pit_price debe ser positivo cuando se proporciona.")

        cutoff = knowledge_cutoff.astimezone(timezone.utc)
        actions = self._repository.list_for_instrument(instrument_id, knowledge_cutoff=cutoff)
        dividends = [row for row in actions if row["action_type"] == "dividend"]
        unique: dict[tuple[str, float, str | None], dict[str, Any]] = {}
        for row in dividends:
            effective = datetime.fromisoformat(str(row["effective_at"]))
            age = (cutoff - effective).total_seconds() / 86400.0
            if age < 0 or age > lookback_days:
                continue
            unique.setdefault((str(row["effective_at"]), float(row["cash_amount"]), row["currency"]), row)

        ordered = sorted(unique.values(), key=lambda row: str(row["effective_at"]))
        if not ordered:
            return DividendAnalysis(0, None, 0.0, None, None, None, "none", None, None, None, None, None, None, None, None, True, cutoff.isoformat())

        currencies = {row["currency"] for row in ordered if row["currency"] is not None}
        currency_consistent = len(currencies) <= 1 and all(row["currency"] is not None for row in ordered)
        currency = next(iter(currencies)) if currency_consistent and currencies else None

        def age_days(row: dict[str, Any]) -> float:
            return (cutoff - datetime.fromisoformat(str(row["effective_at"]))).total_seconds() / 86400.0

        annual_windows: list[list[dict[str, Any]]] = []
        for window_index in range(max(1, lookback_days // 365)):
            lower = window_index * 365
            upper = (window_index + 1) * 365
            annual_windows.append([row for row in ordered if lower < age_days(row) <= upper or (window_index == 0 and age_days(row) == 0)])
        trailing = annual_windows[0]
        prior = annual_windows[1] if len(annual_windows) > 1 else []
        trailing_cash = sum(float(row["cash_amount"]) for row in trailing) if currency_consistent else 0.0
        prior_cash = sum(float(row["cash_amount"]) for row in prior) if currency_consistent else 0.0
        trailing_yield = trailing_cash / pit_price if currency_consistent and trailing and pit_price is not None else None
        cash_60d_rows = [row for row in ordered if 0 <= age_days(row) <= 60]
        cash_per_share_60d = sum(float(row["cash_amount"]) for row in cash_60d_rows) if currency_consistent and cash_60d_rows else None
        yield_60d = cash_per_share_60d / pit_price if cash_per_share_60d is not None and pit_price is not None else None

        dividend_growth_rate = None
        cut_detected = None
        consecutive_full_years_without_cut = None
        if currency_consistent and trailing and prior and prior_cash > 0:
            dividend_growth_rate = (trailing_cash / prior_cash) - 1.0
            cut_detected = dividend_growth_rate < -1e-12
            consecutive_full_years_without_cut = 0
            newer_cash = trailing_cash
            for older_window in annual_windows[1:]:
                if not older_window:
                    break
                older_cash = sum(float(row["cash_amount"]) for row in older_window)
                if older_cash <= 0 or newer_cash < older_cash - 1e-12:
                    break
                consecutive_full_years_without_cut += 1
                newer_cash = older_cash

        if len(ordered) < 2:
            return DividendAnalysis(len(ordered), None, trailing_cash, trailing_yield, cash_per_share_60d, yield_60d, "insufficient_history", None, None, dividend_growth_rate, cut_detected, consecutive_full_years_without_cut, None, None, currency, currency_consistent, cutoff.isoformat())

        dates = [datetime.fromisoformat(str(row["effective_at"])) for row in ordered]
        intervals = [(b - a).total_seconds() / 86400.0 for a, b in zip(dates, dates[1:])]
        typical_days = median(intervals)
        frequency, expected_days = self._classify_frequency(typical_days)
        payments_per_year = 365.2425 / typical_days if typical_days > 0 else None
        regularity = None
        if expected_days is not None:
            deviations = [abs(days - expected_days) / expected_days for days in intervals]
            regularity = max(0.0, min(1.0, 1.0 - sum(deviations) / len(deviations)))

        annualized = trailing_cash if currency_consistent and trailing else None
        cadence_established = expected_days is not None and len(intervals) >= self._MIN_SUSPENSION_INTERVALS and regularity is not None and regularity >= self._MIN_SUSPENSION_REGULARITY
        payment_stability = regularity if cadence_established else None
        suspected_suspension = None
        if cadence_established and expected_days is not None:
            suspected_suspension = age_days(ordered[-1]) > expected_days * self._SUSPENSION_OVERDUE_MULTIPLIER
            if suspected_suspension:
                payment_stability = 0.0
        return DividendAnalysis(len(ordered), annualized, trailing_cash, trailing_yield, cash_per_share_60d, yield_60d, frequency, payments_per_year, regularity, dividend_growth_rate, cut_detected, consecutive_full_years_without_cut, payment_stability, suspected_suspension, currency, currency_consistent, cutoff.isoformat())

    @staticmethod
    def _classify_frequency(days: float) -> tuple[str, float | None]:
        bands = (("monthly", 30.44, 10.0), ("quarterly", 91.31, 25.0), ("semiannual", 182.62, 40.0), ("annual", 365.24, 70.0))
        for name, expected, tolerance in bands:
            if abs(days - expected) <= tolerance:
                return name, expected
        return "irregular", None
