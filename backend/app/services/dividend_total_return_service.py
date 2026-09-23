from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DividendTotalReturn:
    price_return: float
    dividend_return: float
    total_return: float
    dividend_cash_per_share: float
    start_price: float
    end_price: float
    currency: str
    source_provider: str
    knowledge_cutoff: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "priceReturn": self.price_return,
            "dividendReturn": self.dividend_return,
            "totalReturn": self.total_return,
            "dividendCashPerShare": self.dividend_cash_per_share,
            "startPrice": self.start_price,
            "endPrice": self.end_price,
            "currency": self.currency,
            "sourceProvider": self.source_provider,
            "knowledgeCutoff": self.knowledge_cutoff,
            "pitSafe": True,
            "dividendsReinvested": False,
            "productionEligible": False,
            "automaticTrading": False,
        }


class DividendTotalReturnService:
    """PIT total-return decomposition using only observed cash distributions.

    This deliberately does not project future dividends and does not assume
    reinvestment. Price and dividend cash must be expressed in the same currency.
    """

    def calculate(
        self,
        *,
        start_price: float,
        end_price: float,
        dividend_cash_per_share: float,
        currency: str,
        source_provider: str,
        knowledge_cutoff: datetime,
    ) -> DividendTotalReturn:
        if start_price <= 0 or end_price < 0:
            raise ValueError("Los precios deben ser finitos y start_price debe ser positivo.")
        if dividend_cash_per_share < 0:
            raise ValueError("dividend_cash_per_share no puede ser negativo.")
        if not currency.strip():
            raise ValueError("currency es obligatoria.")
        if not source_provider.strip():
            raise ValueError("source_provider es obligatorio para provenance.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")

        start = float(start_price)
        end = float(end_price)
        cash = float(dividend_cash_per_share)
        price_return = end / start - 1.0
        dividend_return = cash / start
        total_return = (end + cash) / start - 1.0
        return DividendTotalReturn(
            price_return=price_return,
            dividend_return=dividend_return,
            total_return=total_return,
            dividend_cash_per_share=cash,
            start_price=start,
            end_price=end,
            currency=currency.strip().upper(),
            source_provider=source_provider.strip(),
            knowledge_cutoff=knowledge_cutoff.astimezone(timezone.utc).isoformat(),
        )
