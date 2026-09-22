from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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
    negative denominators, post-cutoff evidence, or missing provenance.
    """

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
