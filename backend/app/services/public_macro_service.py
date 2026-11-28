from __future__ import annotations

from typing import Any

import httpx


class PublicMacroService:
    """Connectors for public macro sources that do not require secrets."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def get_world_bank_indicator(
        self,
        country: str,
        indicator: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        normalized_country = country.strip()
        normalized_indicator = indicator.strip()
        if not normalized_country or not normalized_indicator:
            raise ValueError("Country and indicator are required.")

        params: dict[str, str | int] = {
            "format": "json",
            "per_page": 20000,
        }
        if start_year is not None or end_year is not None:
            first = start_year if start_year is not None else end_year
            last = end_year if end_year is not None else start_year
            if first is None or last is None:
                raise ValueError("Invalid World Bank date range.")
            if first > last:
                first, last = last, first
            params["date"] = f"{first}:{last}"

        url = (
            "https://api.worldbank.org/v2/country/"
            f"{normalized_country}/indicator/{normalized_indicator}"
        )
        response = self._client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError("Unexpected World Bank response format.")

        return {
            "metadata": payload[0],
            "observations": payload[1] or [],
        }

    def get_ecb_series(
        self,
        flow_ref: str,
        key: str = "",
        start_period: str | None = None,
        end_period: str | None = None,
        last_n_observations: int | None = None,
        include_history: bool = False,
    ) -> Any:
        normalized_flow = flow_ref.strip()
        if not normalized_flow:
            raise ValueError("ECB flow_ref is required.")

        normalized_key = key.strip()
        url = f"https://data-api.ecb.europa.eu/service/data/{normalized_flow}"
        if normalized_key:
            url = f"{url}/{normalized_key}"

        params: dict[str, str | int] = {
            "format": "jsondata",
            "includeHistory": str(include_history).lower(),
        }
        if start_period:
            params["startPeriod"] = start_period
        if end_period:
            params["endPeriod"] = end_period
        if last_n_observations is not None:
            if last_n_observations <= 0:
                raise ValueError("last_n_observations must be positive.")
            params["lastNObservations"] = last_n_observations

        response = self._client.get(
            url,
            params=params,
            headers={"Accept": "application/vnd.sdmx.data+json;version=1.0.0-wd"},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
