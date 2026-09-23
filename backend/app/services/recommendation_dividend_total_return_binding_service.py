from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.dividend_total_return_service import DividendTotalReturnService


@dataclass(frozen=True)
class RecommendationDividendTotalReturnBinding:
    total_return: dict[str, Any]
    price_observed_at: str
    price_retrieved_at: str
    dividend_retrieved_at: str
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "totalReturn": self.total_return,
            "priceObservedAt": self.price_observed_at,
            "priceRetrievedAt": self.price_retrieved_at,
            "dividendRetrievedAt": self.dividend_retrieved_at,
            "productionEligible": self.production_eligible,
            "automaticTrading": False,
            "policy": {
                "pit": "all_component_observation_and_retrieval_times_must_be_known_by_knowledge_cutoff",
                "provenance": "price_and_dividend_providers_are_explicit_and_preserved_separately",
                "authority": "diagnostic_only_not_buy_sell_weighting_or_trading_authority",
            },
        }


class RecommendationDividendTotalReturnBindingService:
    """Bind observed dividend total return to explicit component-level PIT provenance.

    The caller must provide the provider and timestamps for both price and dividend
    evidence. The service never infers provider authority, never projects dividends,
    and never upgrades a diagnostic into production recommendation authority.
    """

    def __init__(self, *, total_return_service: DividendTotalReturnService | None = None) -> None:
        self._total_return_service = total_return_service or DividendTotalReturnService()

    def bind(
        self,
        *,
        start_price: float,
        end_price: float,
        dividend_cash_per_share: float,
        currency: str,
        price_source_provider: str,
        dividend_source_provider: str,
        price_observed_at: datetime,
        price_retrieved_at: datetime,
        dividend_retrieved_at: datetime,
        knowledge_cutoff: datetime,
    ) -> RecommendationDividendTotalReturnBinding:
        cutoff = self._aware_utc(knowledge_cutoff, "knowledge_cutoff")
        observed = self._aware_utc(price_observed_at, "price_observed_at")
        price_retrieved = self._aware_utc(price_retrieved_at, "price_retrieved_at")
        dividend_retrieved = self._aware_utc(dividend_retrieved_at, "dividend_retrieved_at")
        price_provider = str(price_source_provider or "").strip()
        dividend_provider = str(dividend_source_provider or "").strip()
        if not price_provider:
            raise ValueError("price_source_provider es obligatorio.")
        if not dividend_provider:
            raise ValueError("dividend_source_provider es obligatorio.")
        if observed > cutoff or price_retrieved > cutoff or dividend_retrieved > cutoff:
            raise ValueError("La evidencia de retorno total no puede ser posterior al knowledge_cutoff.")
        total_return = self._total_return_service.calculate(
            start_price=start_price,
            end_price=end_price,
            dividend_cash_per_share=dividend_cash_per_share,
            currency=currency,
            source_provider="mixed" if price_provider != dividend_provider else price_provider,
            price_source_provider=price_provider,
            dividend_source_provider=dividend_provider,
            knowledge_cutoff=cutoff,
        ).to_api_dict()
        return RecommendationDividendTotalReturnBinding(
            total_return=total_return,
            price_observed_at=observed.isoformat(),
            price_retrieved_at=price_retrieved.isoformat(),
            dividend_retrieved_at=dividend_retrieved.isoformat(),
        )

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
