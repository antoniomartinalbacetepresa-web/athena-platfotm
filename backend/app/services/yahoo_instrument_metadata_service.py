from __future__ import annotations

from typing import Any

import yfinance as yf


class YahooInstrumentMetadataService:
    """Fetches descriptive/market metadata for one listing from Yahoo."""

    source_id = "yahoo"

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = str(symbol).strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")

        yahoo_symbol = self._to_yahoo_symbol(normalized_symbol)
        ticker = yf.Ticker(yahoo_symbol)

        info = ticker.get_info()
        if not isinstance(info, dict):
            raise RuntimeError(
                f"Yahoo no devolvió metadatos válidos para {normalized_symbol}."
            )

        return {
            "symbol": normalized_symbol,
            "companyName": self._text(
                info.get("longName") or info.get("shortName")
            ),
            "country": self._text(info.get("country")),
            "exchange": self._text(info.get("exchange")),
            "instrumentType": self._instrument_type(info.get("quoteType")),
            "sector": self._text(info.get("sector")),
            "industry": self._text(info.get("industry")),
            "currency": self._upper_text(info.get("currency")),
            "marketCap": self._positive_float(info.get("marketCap")),
            "sourceProvider": self.source_id,
        }

    def _to_yahoo_symbol(self, symbol: str) -> str:
        # Yahoo usa guion para determinadas clases estadounidenses (BRK-B).
        # Se conserva siempre el símbolo normalizado original en la salida.
        if "." in symbol and not self._has_market_suffix(symbol):
            return symbol.replace(".", "-")
        return symbol

    def _has_market_suffix(self, symbol: str) -> bool:
        suffix = symbol.rsplit(".", 1)[-1]
        return suffix in {
            "AS",
            "DE",
            "HK",
            "KS",
            "L",
            "MI",
            "PA",
            "SW",
            "T",
        }

    def _instrument_type(self, value: Any) -> str:
        normalized = str(value or "").strip().upper()
        return {
            "EQUITY": "common_stock",
            "ETF": "etf",
            "MUTUALFUND": "fund",
        }.get(normalized, "unknown")

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _upper_text(self, value: Any) -> str | None:
        normalized = self._text(value)
        return normalized.upper() if normalized is not None else None

    def _positive_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result or result <= 0:
            return None
        return result
