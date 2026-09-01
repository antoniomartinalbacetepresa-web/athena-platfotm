from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository


@dataclass(frozen=True)
class MarketCapCoverageReport:
    usable_count: int
    total_market_cap_usd: float
    top_market_cap_shares: dict[str, float]
    region_market_cap_usd: dict[str, float]
    region_weights: dict[str, float]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "usableCount": self.usable_count,
            "totalMarketCapUsd": self.total_market_cap_usd,
            "topMarketCapShares": dict(self.top_market_cap_shares),
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "regionWeights": dict(self.region_weights),
        }


class MarketCapCoverageService:
    """Analiza concentración y distribución del market cap persistido.

    El informe es diagnóstico. No certifica que la muestra sea representativa
    ni resuelve posibles dobles listados de un mismo emisor.
    """

    _REGIONS = ("america", "europe", "asia")
    _TOP_BUCKETS = (10, 50, 100, 500, 1000)

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)

    def get_report(self) -> MarketCapCoverageReport:
        self._database.initialize()
        rows = self._repository.list_active()

        usable: list[tuple[float, str]] = []
        region_market_cap = {region: 0.0 for region in self._REGIONS}

        for row in rows:
            market_cap = row.get("market_cap_usd")
            region = str(row.get("region_key") or "").strip().lower()
            country = str(row.get("country") or "").strip()

            if (
                not isinstance(market_cap, (int, float))
                or market_cap <= 0
                or not country
                or region not in region_market_cap
            ):
                continue

            cap = float(market_cap)
            usable.append((cap, region))
            region_market_cap[region] += cap

        usable.sort(key=lambda item: item[0], reverse=True)
        total_market_cap = sum(cap for cap, _ in usable)

        top_shares: dict[str, float] = {}
        if total_market_cap > 0:
            cumulative = 0.0
            bucket_index = 0
            for index, (cap, _) in enumerate(usable, start=1):
                cumulative += cap
                while (
                    bucket_index < len(self._TOP_BUCKETS)
                    and index == self._TOP_BUCKETS[bucket_index]
                ):
                    bucket = self._TOP_BUCKETS[bucket_index]
                    top_shares[f"top{bucket}"] = cumulative / total_market_cap
                    bucket_index += 1

            for bucket in self._TOP_BUCKETS:
                key = f"top{bucket}"
                if key not in top_shares:
                    top_shares[key] = 1.0 if usable else 0.0

        region_weights = {
            region: (
                market_cap / total_market_cap
                if total_market_cap > 0
                else 0.0
            )
            for region, market_cap in region_market_cap.items()
        }

        return MarketCapCoverageReport(
            usable_count=len(usable),
            total_market_cap_usd=total_market_cap,
            top_market_cap_shares=top_shares,
            region_market_cap_usd=region_market_cap,
            region_weights=region_weights,
        )
