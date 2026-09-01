from __future__ import annotations

import os
from typing import Any

import httpx


class FredAlfredService:
    """Server-side FRED/ALFRED client with vintage-aware historical access."""

    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        resolved_api_key = (
            api_key
            if api_key is not None
            else os.getenv("FRED_API_KEY", "")
        )
        self._api_key = resolved_api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def get_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        realtime_start: str | None = None,
        realtime_end: str | None = None,
        vintage_dates: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        normalized_series = series_id.strip().upper()
        if not normalized_series:
            raise ValueError("FRED series_id is required.")

        params: dict[str, str] = {
            "series_id": normalized_series,
            "api_key": self._require_api_key(),
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        if vintage_dates:
            params["vintage_dates"] = ",".join(vintage_dates)

        response = self._client.get(
            f"{self.BASE_URL}/series/observations",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected FRED response format.")
        return payload

    def get_vintage_dates(
        self,
        series_id: str,
        realtime_start: str | None = None,
        realtime_end: str | None = None,
    ) -> dict[str, Any]:
        normalized_series = series_id.strip().upper()
        if not normalized_series:
            raise ValueError("FRED series_id is required.")

        params: dict[str, str] = {
            "series_id": normalized_series,
            "api_key": self._require_api_key(),
            "file_type": "json",
        }
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end

        response = self._client.get(
            f"{self.BASE_URL}/series/vintagedates",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected ALFRED vintage response format.")
        return payload

    def _require_api_key(self) -> str:
        if not self._api_key:
            raise RuntimeError(
                "FRED_API_KEY is not configured on the ATHENA backend."
            )
        return self._api_key

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
