from __future__ import annotations

import os
from typing import Any

import httpx


class FinraService:
    """FINRA Query API connector for positioning and market-transparency data."""

    BASE_URL = "https://api.finra.org"

    def __init__(
        self,
        access_token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._access_token = (access_token or os.getenv("FINRA_ACCESS_TOKEN", "")).strip()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def query_dataset(
        self,
        group: str,
        dataset: str,
        *,
        fields: list[str] | None = None,
        limit: int = 1000,
        version: int = 2,
        filters: list[dict[str, Any]] | None = None,
        mock: bool = False,
    ) -> Any:
        normalized_group = group.strip()
        normalized_dataset = dataset.strip()
        if not normalized_group or not normalized_dataset:
            raise ValueError("FINRA group and dataset are required.")
        if limit <= 0:
            raise ValueError("FINRA limit must be positive.")

        dataset_name = (
            normalized_dataset
            if not mock or normalized_dataset.lower().endswith("mock")
            else f"{normalized_dataset}Mock"
        )
        url = f"{self.BASE_URL}/data/group/{normalized_group}/name/{dataset_name}"

        headers = {
            "Accept": "application/json",
            "Data-API-Version": str(version),
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        if filters:
            if not self._access_token and not mock:
                raise RuntimeError(
                    "FINRA_ACCESS_TOKEN is required for authenticated production queries."
                )
            payload: dict[str, Any] = {
                "limit": limit,
                "compareFilters": filters,
            }
            if fields:
                payload["fields"] = fields
            response = self._client.post(url, headers=headers, json=payload)
        else:
            params: dict[str, str | int] = {"limit": limit}
            if fields:
                params["fields"] = ",".join(fields)
            response = self._client.get(url, headers=headers, params=params)

        response.raise_for_status()
        return response.json()

    def get_consolidated_short_interest(
        self,
        *,
        symbol: str | None = None,
        limit: int = 1000,
        mock: bool = False,
    ) -> Any:
        filters = None
        if symbol:
            filters = [
                {
                    "compareType": "equal",
                    "fieldName": "symbolCode",
                    "fieldValue": symbol.strip().upper(),
                }
            ]
        return self.query_dataset(
            "otcmarket",
            "consolidatedShortInterest",
            limit=limit,
            filters=filters,
            mock=mock,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
