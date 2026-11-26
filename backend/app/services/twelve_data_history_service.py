"""Read-only Twelve Data daily equity history, without PIT or licensing claims."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


class TwelveDataHistoryError(ValueError):
    """A provider result could not be safely normalized."""


class TwelveDataHistoryService:
    URL = "https://api.twelvedata.com/time_series"
    MAX_BARS = 5000

    def __init__(
        self,
        client: httpx.Client,
        *,
        api_key: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._client = client
        self._api_key = api_key.strip()
        self._clock = clock

    def get_history(
        self,
        *,
        symbol: str,
        mic: str,
        currency: str,
        exchange_timezone: str,
        start: date,
        end: date,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return ordered rows that are ineligible for PIT research or storage by default."""
        if (
            not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,23}", symbol)
            or not re.fullmatch(r"[A-Z0-9]{4}", mic)
            or not re.fullmatch(r"[A-Z]{3}", currency)
        ):
            raise TwelveDataHistoryError("invalid Twelve Data instrument identity")
        try:
            venue_timezone = ZoneInfo(exchange_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise TwelveDataHistoryError("invalid exchange timezone") from None
        if type(start) is not date or type(end) is not date or start > end:
            raise TwelveDataHistoryError("invalid daily history range")
        if type(limit) is not int or not 1 <= limit <= self.MAX_BARS:
            raise TwelveDataHistoryError("invalid daily history limit")
        if not self._api_key or not self._api_key.isascii() or not self._api_key.isprintable():
            raise TwelveDataHistoryError("Twelve Data key is missing or invalid")

        try:
            response = self._client.get(
                self.URL,
                params={
                    "symbol": symbol, "mic_code": mic, "interval": "1day",
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "outputsize": limit, "adjust": "none",
                },
                headers={"Authorization": f"apikey {self._api_key}"},
                follow_redirects=False,
                timeout=15.0,
            )
        except (httpx.RequestError, httpx.InvalidURL):
            raise TwelveDataHistoryError("Twelve Data history request failed") from None
        if response.status_code == 429:
            raise TwelveDataHistoryError("Twelve Data rate limit reached")
        if response.status_code != 200:
            raise TwelveDataHistoryError("Twelve Data history request rejected")

        try:
            payload = response.json()
        except ValueError:
            raise TwelveDataHistoryError("invalid Twelve Data JSON") from None
        if not isinstance(payload, dict):
            raise TwelveDataHistoryError("invalid Twelve Data history response")
        if payload.get("code") in (429, "429"):
            raise TwelveDataHistoryError("Twelve Data rate limit reached")
        if payload.get("status") != "ok":
            raise TwelveDataHistoryError("Twelve Data history request rejected")
        meta = payload.get("meta")
        expected = {
            "symbol": symbol, "mic_code": mic, "currency": currency,
            "exchange_timezone": exchange_timezone, "interval": "1day",
        }
        if not isinstance(meta, dict) or any(meta.get(key) != value for key, value in expected.items()):
            raise TwelveDataHistoryError("Twelve Data history identity mismatch")
        values = payload.get("values")
        if not isinstance(values, list) or len(values) > limit:
            raise TwelveDataHistoryError("invalid Twelve Data history row count")

        retrieved_at = self._clock()
        if not isinstance(retrieved_at, datetime) or retrieved_at.utcoffset() is None:
            raise TwelveDataHistoryError("history clock must be timezone-aware")
        venue_today = retrieved_at.astimezone(venue_timezone).date()
        retrieved_iso = retrieved_at.astimezone(timezone.utc).isoformat()
        bars = {}
        for row in values:
            session, bar = self._parse_row(row)
            if not start <= session <= end or session >= venue_today or session in bars:
                raise TwelveDataHistoryError("out-of-range, current or duplicate daily session")
            bars[session] = {
                **bar, "symbol": symbol, "mic": mic, "currency": currency,
                "exchangeTimezone": exchange_timezone, "sessionDate": session.isoformat(),
                "retrievedAt": retrieved_iso, "sourceProvider": "twelve_data",
                "historicalPointInTimeEligible": False,
            }
        return [bars[session] for session in sorted(bars)]

    @staticmethod
    def _parse_row(row: object) -> tuple[date, dict[str, float | int]]:
        if not isinstance(row, dict):
            raise TwelveDataHistoryError("invalid Twelve Data history row")
        try:
            session = date.fromisoformat(row["datetime"])
            if session.isoformat() != row["datetime"]:
                raise ValueError
            prices = {field: float(row[field]) for field in ("open", "high", "low", "close")}
            volume = Decimal(str(row["volume"]))
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation):
            raise TwelveDataHistoryError("invalid Twelve Data OHLCV row") from None
        if any(
            isinstance(row[field], bool) or not isfinite(price) or price <= 0
            for field, price in prices.items()
        ):
            raise TwelveDataHistoryError("invalid Twelve Data price")
        if (
            prices["low"] > min(prices["open"], prices["close"])
            or prices["high"] < max(prices["open"], prices["close"])
        ):
            raise TwelveDataHistoryError("inconsistent Twelve Data OHLC range")
        if not volume.is_finite() or not 0 <= volume <= 2**63 - 1 or volume != volume.to_integral_value():
            raise TwelveDataHistoryError("invalid Twelve Data volume")
        return session, {**prices, "volume": int(volume)}
