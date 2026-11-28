from __future__ import annotations

from datetime import date, datetime, time, timezone
import math
import os
from typing import Any, Callable

import httpx


class AlphaVantageCorporateActionService:
    """Independent corporate-action provider adapter for PIT ingestion.

    Alpha Vantage exposes dividends and splits through separate endpoints. This
    adapter translates both payloads into the historical-observation contract
    already consumed by CorporateActionIngestionService; it does not select a
    canonical source and it does not claim production independence by itself.
    """

    BASE_URL = "https://www.alphavantage.co/query"
    SOURCE_PROVIDER = "alpha_vantage"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = (api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")).strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_symbol = self._required_symbol(symbol)
        if not self._api_key:
            raise RuntimeError(
                "ALPHA_VANTAGE_API_KEY is required for the independent corporate-action source."
            )
        lower = self._optional_date(from_date, "from_date")
        upper = self._optional_date(to_date, "to_date")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("from_date no puede ser posterior a to_date.")

        retrieved_at = self._aware_utc(self._clock(), "clock")
        dividends = self._request("DIVIDENDS", normalized_symbol)
        splits = self._request("SPLITS", normalized_symbol)
        observations: list[dict[str, object]] = []

        for item in self._data_rows(dividends, "DIVIDENDS"):
            effective_date = self._row_date(
                item,
                ("ex_dividend_date", "exDividendDate", "effective_date"),
                "DIVIDENDS",
            )
            if not self._in_range(effective_date, lower, upper):
                continue
            effective_at = datetime.combine(effective_date, time.min, tzinfo=timezone.utc)
            if effective_at > retrieved_at:
                # Declared future dividends are useful metadata, but are not yet
                # effective corporate actions for ATHENA's PIT adjustment engine.
                continue
            amount = self._positive_number(
                self._first(item, ("amount", "dividend_amount", "dividendAmount")),
                "DIVIDENDS amount",
            )
            observations.append(
                {
                    "symbol": normalized_symbol,
                    "sourceProvider": self.SOURCE_PROVIDER,
                    "timestamp": effective_at,
                    "retrievedAt": retrieved_at,
                    "dividend": amount,
                    "stockSplit": None,
                }
            )

        for item in self._data_rows(splits, "SPLITS"):
            effective_date = self._row_date(
                item,
                ("effective_date", "effectiveDate", "split_date", "splitDate"),
                "SPLITS",
            )
            if not self._in_range(effective_date, lower, upper):
                continue
            effective_at = datetime.combine(effective_date, time.min, tzinfo=timezone.utc)
            if effective_at > retrieved_at:
                continue
            factor = self._split_factor(
                self._first(item, ("split_factor", "splitFactor", "ratio"))
            )
            observations.append(
                {
                    "symbol": normalized_symbol,
                    "sourceProvider": self.SOURCE_PROVIDER,
                    "timestamp": effective_at,
                    "retrievedAt": retrieved_at,
                    "dividend": None,
                    "stockSplit": factor,
                }
            )

        observations.sort(
            key=lambda row: (
                row["timestamp"],
                0 if row["dividend"] is not None else 1,
            )
        )
        return observations

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, function: str, symbol: str) -> dict[str, Any]:
        response = self._client.get(
            self.BASE_URL,
            params={
                "function": function,
                "symbol": symbol,
                "apikey": self._api_key,
                "datatype": "json",
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Alpha Vantage {function} returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Alpha Vantage {function} returned an invalid payload.")
        if any(key in payload for key in ("Error Message", "Information", "Note")):
            raise RuntimeError(
                f"Alpha Vantage {function} did not return corporate-action data."
            )
        return payload

    def _data_rows(self, payload: dict[str, Any], function: str) -> list[dict[str, Any]]:
        rows = payload.get("data")
        if rows is None:
            rows = payload.get("dividends" if function == "DIVIDENDS" else "splits")
        if not isinstance(rows, list):
            raise RuntimeError(f"Alpha Vantage {function} payload is missing its data array.")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(f"Alpha Vantage {function} contains a malformed row.")
            normalized.append(row)
        return normalized

    def _row_date(
        self,
        row: dict[str, Any],
        keys: tuple[str, ...],
        function: str,
    ) -> date:
        value = self._first(row, keys)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Alpha Vantage {function} row is missing its effective date.")
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"Alpha Vantage {function} returned an invalid effective date."
            ) from exc

    def _split_factor(self, value: Any) -> float:
        if isinstance(value, str) and ":" in value:
            left, right = value.split(":", 1)
            numerator = self._positive_number(left, "SPLITS numerator")
            denominator = self._positive_number(right, "SPLITS denominator")
            factor = numerator / denominator
        else:
            factor = self._positive_number(value, "SPLITS split_factor")
        if not math.isfinite(factor) or factor <= 0:
            raise RuntimeError("Alpha Vantage SPLITS returned an invalid split factor.")
        return factor

    def _positive_number(self, value: Any, field: str) -> float:
        if isinstance(value, bool):
            raise RuntimeError(f"Alpha Vantage {field} must be numeric.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Alpha Vantage {field} must be numeric.") from exc
        if not math.isfinite(number) or number <= 0:
            raise RuntimeError(f"Alpha Vantage {field} must be finite and positive.")
        return number

    def _first(self, row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in row:
                return row[key]
        return None

    def _required_symbol(self, value: object) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise ValueError("symbol es obligatorio.")
        return normalized

    def _optional_date(self, value: str | None, field: str) -> date | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} no puede estar vacío.")
        try:
            return date.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field} debe usar formato YYYY-MM-DD.") from exc

    def _in_range(self, value: date, lower: date | None, upper: date | None) -> bool:
        if lower is not None and value < lower:
            return False
        if upper is not None and value > upper:
            return False
        return True

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
