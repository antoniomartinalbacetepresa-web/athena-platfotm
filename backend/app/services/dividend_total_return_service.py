from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import unicodedata
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
    start_observed_at: str | None
    end_observed_at: str | None
    dividend_observed_at: str | None
    pit_safe: bool

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
            "startObservedAt": self.start_observed_at,
            "endObservedAt": self.end_observed_at,
            "dividendObservedAt": self.dividend_observed_at,
            "pitSafe": self.pit_safe,
            "dividendsReinvested": False,
            "productionEligible": False,
            "automaticTrading": False,
        }


class DividendTotalReturnService:
    """Research-only total-return decomposition with conservative PIT evidence.

    This deliberately does not project future dividends and does not assume
    reinvestment. Price and dividend cash must be expressed in the same currency.
    Price and dividend provenance are kept separately so a mixed-source total
    return cannot be presented as if every component came from one provider.
    """

    @staticmethod
    def _currency(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("currency debe ser un código de tres letras ASCII.")
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("currency debe ser un código de tres letras ASCII.")
        return normalized

    @staticmethod
    def _provider(value: str | None, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} es obligatorio para provenance.")
        normalized = value.strip()
        provider_key = "".join(
            c for c in unicodedata.normalize("NFKC", normalized).casefold()
            if c.isalnum()
        )
        if "fmp" in provider_key or "financialmodelingprep" in provider_key:
            raise ValueError(f"{field} no puede utilizar FMP.")
        return normalized

    @staticmethod
    def _finite_amount(value: Any) -> float:
        # Reject bool and numeric strings instead of silently casting them
        # into valid-looking market observations.
        if isinstance(value, (bool, str, bytes)):
            raise ValueError("Los precios y dividendos deben ser finitos.")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Los precios y dividendos deben ser finitos.") from exc
        if not math.isfinite(result):
            raise ValueError("Los precios y dividendos deben ser finitos.")
        return result

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
        start_observed_at: datetime | None = None,
        end_observed_at: datetime | None = None,
        dividend_observed_at: datetime | None = None,
    ) -> DividendTotalReturn:
        values = tuple(self._finite_amount(value) for value in (start_price, end_price, dividend_cash_per_share))
        start, end, cash = values
        if start <= 0 or end < 0:
            raise ValueError("start_price debe ser positivo y end_price no negativo.")
        if cash < 0:
            raise ValueError("dividend_cash_per_share no puede ser negativo.")
        normalized_currency = self._currency(currency)
        provider = self._provider(source_provider, "source_provider")
        price_provider = provider if price_source_provider is None else self._provider(price_source_provider, "price_source_provider")
        dividend_provider = provider if dividend_source_provider is None else self._provider(dividend_source_provider, "dividend_source_provider")
        if not isinstance(knowledge_cutoff, datetime) or knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe ser un datetime con zona horaria.")
        cutoff_utc = knowledge_cutoff.astimezone(timezone.utc)
        if cutoff_utc > datetime.now(timezone.utc):
            raise ValueError("knowledge_cutoff no puede ser una fecha futura.")

        # A cutoff alone cannot establish when each input became knowable.
        # Caller-provided timestamps are not independent production provenance.
        observed: dict[str, str | None] = {}
        for name, value in (
            ("start_observed_at", start_observed_at),
            ("end_observed_at", end_observed_at),
            ("dividend_observed_at", dividend_observed_at),
        ):
            if value is None:
                observed[name] = None
                continue
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} debe ser un datetime con zona horaria.")
            timestamp = value.astimezone(timezone.utc)
            if timestamp > cutoff_utc:
                raise ValueError(f"{name} no puede superar knowledge_cutoff.")
            observed[name] = timestamp.isoformat()
        if (
            observed["start_observed_at"] is not None
            and observed["end_observed_at"] is not None
            and observed["start_observed_at"] > observed["end_observed_at"]
        ):
            raise ValueError("start_observed_at no puede ser posterior a end_observed_at.")
        pit_safe = all(value is not None for value in observed.values())

        price_return = end / start - 1.0
        dividend_return = cash / start
        total_return = (end + cash) / start - 1.0
        if not all(math.isfinite(value) for value in (price_return, dividend_return, total_return)):
            raise ValueError("Los retornos calculados deben ser finitos.")
        return DividendTotalReturn(
            price_return=price_return,
            dividend_return=dividend_return,
            total_return=total_return,
            dividend_cash_per_share=cash,
            start_price=start,
            end_price=end,
            currency=normalized_currency,
            source_provider=provider,
            price_source_provider=price_provider,
            dividend_source_provider=dividend_provider,
            knowledge_cutoff=cutoff_utc.isoformat(),
            start_observed_at=observed["start_observed_at"],
            end_observed_at=observed["end_observed_at"],
            dividend_observed_at=observed["dividend_observed_at"],
            pit_safe=pit_safe,
        )
