from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.financial_period_repository import FinancialPeriodRepository


@dataclass(frozen=True)
class DividendSustainability:
    earnings_payout_ratio: float | None
    fcf_payout_ratio: float | None
    earnings_covered: bool | None
    fcf_covered: bool | None
    sustainability_score: float | None
    source_provider: str | None
    source_timestamp: str | None
    retrieved_at: str | None
    knowledge_cutoff: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "earningsPayoutRatio": self.earnings_payout_ratio,
            "fcfPayoutRatio": self.fcf_payout_ratio,
            "earningsCovered": self.earnings_covered,
            "fcfCovered": self.fcf_covered,
            "sustainabilityScore": self.sustainability_score,
            "sourceProvider": self.source_provider,
            "sourceTimestamp": self.source_timestamp,
            "retrievedAt": self.retrieved_at,
            "knowledgeCutoff": self.knowledge_cutoff,
            "pitSafe": True,
        }


class DividendSustainabilityService:
    """Evaluate dividend coverage only from temporally comparable PIT fundamentals.

    Inputs are aggregate cash amounts for the same reporting window and currency.
    The service deliberately refuses to infer payout from per-share/aggregate mixes,
    negative denominators, post-cutoff evidence, or missing provenance. Repository-
    backed analysis requires an explicit provider so independent sources are never
    silently promoted to authority or blended when they disagree.
    """

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = FinancialPeriodRepository(database=self._database)

    def analyze_latest_period(
        self,
        *,
        instrument_id: int,
        knowledge_cutoff: datetime,
        source_provider: str,
    ) -> DividendSustainability:
        """Analyze the latest PIT-visible period for one explicitly selected provider.

        All payout inputs come from one immutable financial-period revision, which
        guarantees a common economic window and currency. Provider selection stays
        outside this service: reconciliation/authority must not be automated here.
        """
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        provider = str(source_provider or "").strip()
        if not provider:
            raise ValueError("source_provider es obligatorio.")
        rows = [
            row for row in self._repository.list_latest_for_instrument(
                instrument_id, knowledge_cutoff=knowledge_cutoff
            )
            if row["source_provider"] == provider
        ]
        if not rows:
            return self.analyze(
                dividends_paid=None,
                net_income=None,
                free_cash_flow=None,
                knowledge_cutoff=knowledge_cutoff,
                source_provider=None,
                retrieved_at=None,
                comparable_window=False,
                currency_consistent=False,
            )
        row = max(rows, key=lambda item: (item["period_end"], item["retrieved_at"], item["id"]))
        return self.analyze(
            dividends_paid=row["dividends_paid"],
            net_income=row["net_income"],
            free_cash_flow=row["free_cash_flow"],
            knowledge_cutoff=knowledge_cutoff,
            source_provider=row["source_provider"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            source_timestamp=(
                datetime.fromisoformat(row["source_timestamp"])
                if row["source_timestamp"] is not None else None
            ),
            comparable_window=True,
            currency_consistent=True,
        )

    @staticmethod
    def analyze(
        *,
        dividends_paid: float | None,
        net_income: float | None,
        free_cash_flow: float | None,
        knowledge_cutoff: datetime,
        source_provider: str | None,
        retrieved_at: datetime | None,
        source_timestamp: datetime | None = None,
        comparable_window: bool = False,
        currency_consistent: bool = False,
    ) -> DividendSustainability:
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")
        cutoff = knowledge_cutoff.astimezone(timezone.utc)
        provider = str(source_provider or "").strip() or None
        retrieved = DividendSustainabilityService._utc(retrieved_at, "retrieved_at") if retrieved_at is not None else None
        source = DividendSustainabilityService._utc(source_timestamp, "source_timestamp") if source_timestamp is not None else None
        evidence_valid = comparable_window and currency_consistent and provider is not None and retrieved is not None
        if evidence_valid and retrieved > cutoff:
            evidence_valid = False
        if evidence_valid and source is not None and (source > retrieved or source > cutoff):
            evidence_valid = False
        if dividends_paid is not None and dividends_paid < 0:
            raise ValueError("dividends_paid no puede ser negativo.")

        earnings_ratio = fcf_ratio = None
        if evidence_valid and dividends_paid is not None:
            if net_income is not None and net_income > 0:
                earnings_ratio = dividends_paid / net_income
            if free_cash_flow is not None and free_cash_flow > 0:
                fcf_ratio = dividends_paid / free_cash_flow

        earnings_covered = earnings_ratio <= 1.0 if earnings_ratio is not None else None
        fcf_covered = fcf_ratio <= 1.0 if fcf_ratio is not None else None
        ratios = [value for value in (earnings_ratio, fcf_ratio) if value is not None]
        score = None
        if ratios:
            # 1.0 at zero payout, 0.0 at or above 100%; descriptive, not a recommendation.
            score = sum(max(0.0, min(1.0, 1.0 - value)) for value in ratios) / len(ratios)

        return DividendSustainability(
            earnings_payout_ratio=earnings_ratio,
            fcf_payout_ratio=fcf_ratio,
            earnings_covered=earnings_covered,
            fcf_covered=fcf_covered,
            sustainability_score=score,
            source_provider=provider if evidence_valid else None,
            source_timestamp=source.isoformat() if evidence_valid and source is not None else None,
            retrieved_at=retrieved.isoformat() if evidence_valid and retrieved is not None else None,
            knowledge_cutoff=cutoff.isoformat(),
        )

    @staticmethod
    def _utc(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
