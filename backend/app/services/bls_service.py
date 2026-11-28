from __future__ import annotations

import os
from typing import Any

import httpx


class BlsService:
    """Official U.S. Bureau of Labor Statistics Public Data API connector."""

    BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(
        self,
        registration_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._registration_key = (
            registration_key or os.getenv("BLS_REGISTRATION_KEY", "")
        ).strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def get_series(
        self,
        series_ids: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        *,
        catalog: bool = False,
        calculations: bool = False,
        annual_average: bool = False,
        aspects: bool = False,
    ) -> dict[str, Any]:
        normalized_ids = [series_id.strip() for series_id in series_ids if series_id.strip()]
        if not normalized_ids:
            raise ValueError("At least one BLS series ID is required.")

        payload: dict[str, Any] = {"seriesid": normalized_ids}

        if start_year is not None or end_year is not None:
            first = start_year if start_year is not None else end_year
            last = end_year if end_year is not None else start_year
            if first is None or last is None:
                raise ValueError("Invalid BLS date range.")
            if first > last:
                first, last = last, first
            payload["startyear"] = str(first)
            payload["endyear"] = str(last)

        optional_features = catalog or calculations or annual_average or aspects
        if optional_features and not self._registration_key:
            raise RuntimeError(
                "BLS_REGISTRATION_KEY is required for optional BLS API features."
            )

        if self._registration_key:
            payload["registrationkey"] = self._registration_key
        if catalog:
            payload["catalog"] = True
        if calculations:
            payload["calculations"] = True
        if annual_average:
            payload["annualaverage"] = True
        if aspects:
            payload["aspects"] = True

        response = self._client.post(self.BASE_URL, json=payload)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            messages = data.get("message") or []
            detail = "; ".join(str(message) for message in messages)
            raise ValueError(detail or "BLS request failed.")

        return data

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
