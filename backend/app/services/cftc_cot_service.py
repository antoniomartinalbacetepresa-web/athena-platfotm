from __future__ import annotations

from typing import Any

import httpx


class CftcCotService:
    """Read-only connector for CFTC Commitments of Traders public datasets."""

    BASE_URL = "https://publicreporting.cftc.gov/resource"
    DATASETS = {
        "legacy_futures": "6dca-aqww",
        "legacy_combined": "jun7-fc8e",
        "disaggregated_futures": "72hh-3qpy",
        "disaggregated_combined": "kh3c-gbw2",
        "tff_futures": "gpe5-46if",
        "tff_combined": "yw9f-hn96",
    }

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def get_rows(
        self,
        dataset: str,
        limit: int = 1000,
        where: str | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        dataset_id = self.DATASETS.get(dataset)
        if dataset_id is None:
            raise ValueError(f"Unsupported CFTC COT dataset: {dataset}")
        if limit <= 0 or limit > 50000:
            raise ValueError("CFTC limit must be between 1 and 50000.")

        params: dict[str, str | int] = {"$limit": limit}
        if where:
            params["$where"] = where
        if order:
            params["$order"] = order

        response = self._client.get(
            f"{self.BASE_URL}/{dataset_id}.json",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Unexpected CFTC COT response format.")
        return [row for row in payload if isinstance(row, dict)]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
