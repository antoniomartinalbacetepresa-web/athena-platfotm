from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yfinance as yf


@dataclass(frozen=True)
class FxRate:
    currency: str
    usd_rate: float
    source_symbol: str


class YahooFxService:
    _USD = "USD"

    # Known Yahoo conventions retained for compatibility and fewer probes.
    _DIRECT_TO_USD_SYMBOLS: dict[str, str] = {
        "EUR": "EURUSD=X",
    }

    _USD_TO_LOCAL_SYMBOLS: dict[str, str] = {
        "JPY": "JPY=X",
        "KRW": "KRW=X",
        "HKD": "HKD=X",
    }

    def __init__(self) -> None:
        self._rate_cache: dict[str, FxRate] = {}

    def get_usd_rate(
        self,
        currency: str,
    ) -> FxRate:
        normalized_currency = self._normalize_currency(
            currency
        )

        cached = self._rate_cache.get(normalized_currency)
        if cached is not None:
            return cached

        rate = self._load_usd_rate(normalized_currency)
        self._rate_cache[normalized_currency] = rate
        return rate

    def _load_usd_rate(
        self,
        normalized_currency: str,
    ) -> FxRate:
        if normalized_currency == self._USD:
            return FxRate(
                currency=self._USD,
                usd_rate=1.0,
                source_symbol="USD",
            )

        direct_symbol = self._DIRECT_TO_USD_SYMBOLS.get(
            normalized_currency
        )

        if direct_symbol is not None:
            quote = self._get_positive_last_price(
                direct_symbol
            )

            return FxRate(
                currency=normalized_currency,
                usd_rate=quote,
                source_symbol=direct_symbol,
            )

        inverse_symbol = self._USD_TO_LOCAL_SYMBOLS.get(
            normalized_currency
        )

        if inverse_symbol is not None:
            quote = self._get_positive_last_price(
                inverse_symbol
            )

            return FxRate(
                currency=normalized_currency,
                usd_rate=1.0 / quote,
                source_symbol=inverse_symbol,
            )

        generic_direct = f"{normalized_currency}USD=X"
        try:
            quote = self._get_positive_last_price(
                generic_direct
            )
            return FxRate(
                currency=normalized_currency,
                usd_rate=quote,
                source_symbol=generic_direct,
            )
        except RuntimeError:
            generic_inverse = f"USD{normalized_currency}=X"
            try:
                quote = self._get_positive_last_price(
                    generic_inverse
                )
                return FxRate(
                    currency=normalized_currency,
                    usd_rate=1.0 / quote,
                    source_symbol=generic_inverse,
                )
            except RuntimeError as inverse_error:
                raise ValueError(
                    "No se pudo obtener una conversión a USD válida "
                    f"para la moneda {normalized_currency}."
                ) from inverse_error

    def convert_to_usd(
        self,
        amount: float,
        currency: str,
    ) -> float:
        normalized_amount = self._to_positive_float(
            amount
        )

        if normalized_amount is None:
            raise ValueError(
                "El importe debe ser un número positivo."
            )

        fx_rate = self.get_usd_rate(
            currency
        )

        return normalized_amount * fx_rate.usd_rate

    def clear_cache(self) -> None:
        self._rate_cache.clear()

    def _get_positive_last_price(
        self,
        symbol: str,
    ) -> float:
        ticker = yf.Ticker(symbol)

        try:
            fast_info = ticker.fast_info

            value = self._get_fast_info_value(
                fast_info,
                "lastPrice",
                "last_price",
            )
        except Exception as exc:
            raise RuntimeError(
                "No se pudo obtener el tipo de cambio "
                f"para {symbol}."
            ) from exc

        result = self._to_positive_float(
            value
        )

        if result is None:
            raise RuntimeError(
                "Yahoo no devolvió un tipo de cambio válido "
                f"para {symbol}."
            )

        return result

    def _get_fast_info_value(
        self,
        fast_info: Any,
        primary_key: str,
        legacy_key: str,
    ) -> Any:
        value = fast_info.get(primary_key)

        if value is not None:
            return value

        return fast_info.get(legacy_key)

    def _normalize_currency(
        self,
        currency: str,
    ) -> str:
        normalized = currency.strip().upper()

        if not normalized:
            raise ValueError(
                "La moneda no puede estar vacía."
            )

        return normalized

    def _to_positive_float(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if result != result:
            return None

        if result <= 0:
            return None

        return result
