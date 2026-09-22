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
    frequency: str
    payments_per_year: float | None
    regularity_score: float | None
    currency: str | None
    currency_consistent: bool
    knowledge_cutoff: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "paymentCount": self.payment_count,
            "annualizedCashPerShare": self.annualized_cash_per_share,
            "trailingCashPerShare": self.trailing_cash_per_share,
            "frequency": self.frequency,
            "paymentsPerYear": self.payments_per_year,
            "regularityScore": self.regularity_score,
            "currency": self.currency,
            "currencyConsistent": self.currency_consistent,
            "knowledgeCutoff": self.knowledge_cutoff,
            "pitSafe": True,
        }


class DividendAnalysisService:
    """PIT-safe dividend cadence and cash-distribution diagnostics.

    This service intentionally does not turn dividend yield into a recommendation.
    It supplies evidence for total-return/recommendation engines. Duplicate economic
    events learned from multiple providers are collapsed before cadence is measured.
    """

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)

    def analyze(
        self,
        *,
        instrument_id: int,
        knowledge_cutoff: datetime,
        lookback_days: int = 550,
    ) -> DividendAnalysis:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")
        if lookback_days < 365:
            raise ValueError("lookback_days debe ser al menos 365 para inferir frecuencia.")

        cutoff = knowledge_cutoff.astimezone(timezone.utc)
        actions = self._repository.list_for_instrument(
            instrument_id,
            knowledge_cutoff=cutoff,
        )
        dividends = [row for row in actions if row["action_type"] == "dividend"]

        # Same economic event may arrive from independent providers. Count it once.
        unique: dict[tuple[str, float, str | None], dict[str, Any]] = {}
        for row in dividends:
            effective = datetime.fromisoformat(str(row["effective_at"]))
            if (cutoff - effective).days > lookback_days:
                continue
            key = (str(row["effective_at"]), float(row["cash_amount"]), row["currency"])
            unique.setdefault(key, row)

        ordered = sorted(unique.values(), key=lambda row: str(row["effective_at"]))
        if not ordered:
            return DividendAnalysis(0, None, 0.0, "none", None, None, None, True, cutoff.isoformat())

        currencies = {row["currency"] for row in ordered if row["currency"] is not None}
        currency_consistent = len(currencies) <= 1 and all(row["currency"] is not None for row in ordered)
        currency = next(iter(currencies)) if currency_consistent and currencies else None

        trailing = [
            row for row in ordered
            if 0 <= (cutoff - datetime.fromisoformat(str(row["effective_at"]))).days <= 365
        ]
        trailing_cash = sum(float(row["cash_amount"]) for row in trailing) if currency_consistent else 0.0

        if len(ordered) < 2:
            return DividendAnalysis(len(ordered), None, trailing_cash, "insufficient_history", None, None, currency, currency_consistent, cutoff.isoformat())

        dates = [datetime.fromisoformat(str(row["effective_at"])) for row in ordered]
        intervals = [(b - a).total_seconds() / 86400.0 for a, b in zip(dates, dates[1:])]
        typical_days = median(intervals)
        frequency, expected_days = self._classify_frequency(typical_days)
        payments_per_year = 365.2425 / typical_days if typical_days > 0 else None
        regularity = None
        if expected_days is not None:
            deviations = [abs(days - expected_days) / expected_days for days in intervals]
            regularity = max(0.0, min(1.0, 1.0 - sum(deviations) / len(deviations)))

        annualized = None
        if currency_consistent and trailing:
            annualized = trailing_cash

        return DividendAnalysis(
            len(ordered), annualized, trailing_cash, frequency, payments_per_year,
            regularity, currency, currency_consistent, cutoff.isoformat(),
        )

    @staticmethod
    def _classify_frequency(days: float) -> tuple[str, float | None]:
        bands = (
            ("monthly", 30.44, 10.0),
            ("quarterly", 91.31, 25.0),
            ("semiannual", 182.62, 40.0),
            ("annual", 365.24, 70.0),
        )
        for name, expected, tolerance in bands:
            if abs(days - expected) <= tolerance:
                return name, expected
        return "irregular", None
