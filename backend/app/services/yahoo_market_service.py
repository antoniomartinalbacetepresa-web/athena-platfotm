from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

import yfinance as yf


class YahooMarketService:
    PROVIDER_ID = "yahoo"

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        normalized_symbol = self._normalize_symbol(symbol)
        retrieved_at = datetime.now(timezone.utc)

        ticker = yf.Ticker(normalized_symbol)
        fast_info = ticker.fast_info

        current_price = self._to_float(
            self._get_fast_info_value(fast_info, "lastPrice", "last_price")
        )
        previous_close = self._to_float(
            self._get_fast_info_value(fast_info, "previousClose", "previous_close")
        )
        open_price = self._to_float(
            self._get_fast_info_value(fast_info, "open", "open")
        )
        day_high = self._to_float(
            self._get_fast_info_value(fast_info, "dayHigh", "day_high")
        )
        day_low = self._to_float(
            self._get_fast_info_value(fast_info, "dayLow", "day_low")
        )
        volume = self._to_float(
            self._get_fast_info_value(fast_info, "lastVolume", "last_volume")
        )

        currency = self._optional_text(
            self._get_fast_info_value(fast_info, "currency", "currency")
        )
        exchange = self._optional_text(
            self._get_fast_info_value(fast_info, "exchange", "exchange")
        )
        quote_type = self._optional_text(
            self._get_fast_info_value(fast_info, "quoteType", "quote_type")
        )
        timezone_name = self._optional_text(
            self._get_fast_info_value(fast_info, "timezone", "timezone")
        )

        if current_price is None:
            history = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False,
            )

            if history.empty:
                return None

            latest = history.iloc[-1]
            current_price = self._to_float(latest.get("Close"))
            open_price = (
                open_price
                if open_price is not None
                else self._to_float(latest.get("Open"))
            )
            day_high = (
                day_high
                if day_high is not None
                else self._to_float(latest.get("High"))
            )
            day_low = (
                day_low
                if day_low is not None
                else self._to_float(latest.get("Low"))
            )
            volume = (
                volume
                if volume is not None
                else self._to_float(latest.get("Volume"))
            )
            if previous_close is None and len(history.index) >= 2:
                previous_close = self._to_float(history.iloc[-2].get("Close"))

        if current_price is None:
            return None

        change = None
        change_percentage = None
        if previous_close is not None:
            change = current_price - previous_close
            if previous_close != 0:
                change_percentage = (change / previous_close) * 100

        return {
            "symbol": normalized_symbol,
            "timestamp": retrieved_at.isoformat(),
            "retrievedAt": retrieved_at.isoformat(),
            "sourceProvider": self.PROVIDER_ID,
            "currency": currency.upper() if currency is not None else None,
            "exchange": exchange,
            "quoteType": quote_type,
            "exchangeTimezone": timezone_name,
            "open": open_price,
            "high": day_high,
            "low": day_low,
            "close": current_price,
            "adjustedClose": current_price,
            "volume": volume,
            "change": change,
            "changePercentage": change_percentage,
        }

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_symbol = self._normalize_symbol(symbol)

        parsed_from_date = self._parse_date(from_date)
        parsed_to_date = self._parse_date(to_date)
        self._validate_date_range(parsed_from_date, parsed_to_date)

        yahoo_end_date = self._inclusive_to_exclusive_date(to_date)
        ticker = yf.Ticker(normalized_symbol)
        history = ticker.history(
            start=from_date,
            end=yahoo_end_date,
            period=None if from_date or to_date else "1mo",
            interval="1d",
            auto_adjust=False,
        )

        if history.empty:
            return []

        retrieved_at = datetime.now(timezone.utc).isoformat()
        result: list[dict[str, Any]] = []

        for index, row in history.iterrows():
            timestamp = index.to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)

            close_price = self._to_float(row.get("Close"))
            adjusted_close = self._to_float(row.get("Adj Close"))
            if adjusted_close is None:
                adjusted_close = close_price

            result.append(
                {
                    "symbol": normalized_symbol,
                    "timestamp": timestamp.isoformat(),
                    "retrievedAt": retrieved_at,
                    "sourceProvider": self.PROVIDER_ID,
                    "open": self._to_float(row.get("Open")),
                    "high": self._to_float(row.get("High")),
                    "low": self._to_float(row.get("Low")),
                    "close": close_price,
                    "adjustedClose": adjusted_close,
                    "volume": self._to_float(row.get("Volume")),
                    "change": None,
                    "changePercentage": None,
                }
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

    def _parse_date(self, value: str | None) -> date | None:
        if value is None:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                "La fecha debe tener formato YYYY-MM-DD y ser una fecha válida."
            ) from exc

    def _validate_date_range(
        self,
        from_date: date | None,
        to_date: date | None,
    ) -> None:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ValueError(
                "La fecha inicial no puede ser posterior a la fecha final."
            )

    def _inclusive_to_exclusive_date(self, value: str | None) -> str | None:
        parsed = self._parse_date(value)
        if parsed is None:
            return None
        return (parsed + timedelta(days=1)).isoformat()

    def _normalize_symbol(self, symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("El símbolo no puede estar vacío.")
        return normalized

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _to_float(self, value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        return result
