from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
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
    price_source_provider: str
    dividend_source_provider: str
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
            "priceSourceProvider": self.price_source_provider,
            "dividendSourceProvider": self.dividend_source_provider,
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
    Price and dividend provenance are kept separately so a mixed-source total
    return cannot be presented as if every component came from one provider.
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
        price_source_provider: str | None = None,
        dividend_source_provider: str | None = None,
    ) -> DividendTotalReturn:
        values = (float(start_price), float(end_price), float(dividend_cash_per_share))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Los precios y dividendos deben ser finitos.")
        start, end, cash = values
        if start <= 0 or end < 0:
            raise ValueError("start_price debe ser positivo y end_price no negativo.")
        if cash < 0:
            raise ValueError("dividend_cash_per_share no puede ser negativo.")
        if not currency.strip():
            raise ValueError("currency es obligatoria.")
        provider = source_provider.strip()
        if not provider:
            raise ValueError("source_provider es obligatorio para provenance.")
        price_provider = provider if price_source_provider is None else price_source_provider.strip()
        dividend_provider = provider if dividend_source_provider is None else dividend_source_provider.strip()
        if not price_provider:
            raise ValueError("price_source_provider no puede estar vacío.")
        if not dividend_provider:
            raise ValueError("dividend_source_provider no puede estar vacío.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")

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
            source_provider=provider,
            price_source_provider=price_provider,
            dividend_source_provider=dividend_provider,
            knowledge_cutoff=knowledge_cutoff.astimezone(timezone.utc).isoformat(),
        )
