from __future__ import annotations

import os
from typing import Any

import httpx


class EiaService:
    """Official U.S. Energy Information Administration API v2 connector."""

    BASE_URL = "https://api.eia.gov/v2"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = (api_key or os.getenv("EIA_API_KEY", "")).strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def get_data(
        self,
        route: str,
        *,
        data: list[str] | None = None,
        facets: dict[str, list[str]] | None = None,
        frequency: str | None = None,
        start: str | None = None,
        end: str | None = None,
        length: int = 5000,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("EIA_API_KEY is not configured.")

        normalized_route = route.strip().strip("/")
        if not normalized_route:
            raise ValueError("EIA route is required.")
        if length <= 0 or offset < 0:
            raise ValueError("Invalid EIA pagination values.")

        params: list[tuple[str, str | int]] = [
            ("api_key", self._api_key),
            ("length", length),
            ("offset", offset),
        ]
        if frequency:
            params.append(("frequency", frequency))
        if start:
            params.append(("start", start))
        if end:
            params.append(("end", end))
        for index, field in enumerate(data or []):
            normalized = field.strip()
            if normalized:
                params.append((f"data[{index}]", normalized))
        for facet, values in (facets or {}).items():
            normalized_facet = facet.strip()
            if not normalized_facet:
                continue
            for index, value in enumerate(values):
                normalized_value = value.strip()
                if normalized_value:
                    params.append(
                        (f"facets[{normalized_facet}][{index}]", normalized_value)
                    )

        response = self._client.get(
            f"{self.BASE_URL}/{normalized_route}/data/",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if "response" not in payload:
            raise ValueError("Unexpected EIA response format.")
        return payload

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
