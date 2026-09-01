from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.yahoo_market_universe_service import YahooMarketUniverseService


class MarketUniverseFallback(Protocol):
    def get_universe(self) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class MarketUniverseQualityReport:
    active_count: int
    market_cap_ready_count: int
    country_ready_count: int
    globally_usable_count: int
    region_counts: dict[str, int]
    represented_regions: tuple[str, ...]
    is_global_ready: bool
    using_fallback: bool

    def to_api_dict(self) -> dict[str, Any]:
        coverage = (
            self.globally_usable_count / self.active_count
            if self.active_count > 0
            else 0.0
        )

        return {
            "activeCount": self.active_count,
            "marketCapReadyCount": self.market_cap_ready_count,
            "countryReadyCount": self.country_ready_count,
            "globallyUsableCount": self.globally_usable_count,
            "usableCoverage": coverage,
            "regionCounts": dict(self.region_counts),
            "representedRegions": list(self.represented_regions),
            "requiredRegions": ["america", "europe", "asia"],
            "isGlobalReady": self.is_global_ready,
            "usingFallback": self.using_fallback,
        }


class PersistedMarketUniverseService:
    """Sirve un universo persistido sólo cuando es apto para pesos globales."""

    _REQUIRED_REGIONS = frozenset({"america", "europe", "asia"})
    _REGION_ORDER = ("america", "europe", "asia")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        fallback_service: MarketUniverseFallback | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)
        self._fallback_service = (
            fallback_service
            if fallback_service is not None
            else YahooMarketUniverseService()
        )

    def get_universe(self) -> list[dict[str, Any]]:
        rows = self._load_active_rows()
        report = self._build_quality_report(rows)

        if not report.is_global_ready:
            return self._fallback_service.get_universe()

        return [self._to_api_asset(row) for row in rows]

    def get_quality_report(self) -> MarketUniverseQualityReport:
        rows = self._load_active_rows()
        return self._build_quality_report(rows)

    def _load_active_rows(self) -> list[dict[str, Any]]:
        self._database.initialize()
        return self._repository.list_active()

    def _build_quality_report(
        self,
        rows: list[dict[str, Any]],
    ) -> MarketUniverseQualityReport:
        market_cap_ready_count = 0
        country_ready_count = 0
        globally_usable_count = 0
        region_counts = {
            region: 0
            for region in self._REGION_ORDER
        }

        for row in rows:
            market_cap = row.get("market_cap_usd")
            has_market_cap = (
                isinstance(market_cap, (int, float))
                and market_cap > 0
            )
            if has_market_cap:
                market_cap_ready_count += 1

            country = str(row.get("country") or "").strip()
            has_country = bool(country)
            if has_country:
                country_ready_count += 1

            region_key = str(row.get("region_key") or "").strip().lower()
            has_supported_region = region_key in self._REQUIRED_REGIONS

            if has_market_cap and has_country and has_supported_region:
                globally_usable_count += 1
                region_counts[region_key] += 1

        represented_regions = tuple(
            region
            for region in self._REGION_ORDER
            if region_counts[region] > 0
        )
        is_global_ready = (
            set(represented_regions) == self._REQUIRED_REGIONS
        )

        return MarketUniverseQualityReport(
            active_count=len(rows),
            market_cap_ready_count=market_cap_ready_count,
            country_ready_count=country_ready_count,
            globally_usable_count=globally_usable_count,
            region_counts=region_counts,
            represented_regions=represented_regions,
            is_global_ready=is_global_ready,
            using_fallback=not is_global_ready,
        )

    def _to_api_asset(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": row["symbol"],
            "companyName": row["company_name"],
            "marketCap": row["market_cap_usd"],
            "marketCapLocal": row["market_cap_local"],
            "marketCapCurrency": row["market_cap_local_currency"],
            "country": row["country"],
            "exchange": row["exchange"],
            "exchangeShortName": row["exchange_short_name"],
            "regionKey": row["region_key"],
            "issuerId": row["issuer_id"],
            "instrumentId": row["instrument_id"],
            "instrumentType": row["instrument_type"],
            "isPrimaryListing": bool(row["is_primary_listing"]),
            "sector": row["sector"],
            "industry": row["industry"],
            "currency": row["currency"],
            "sourceProvider": row["source_provider"],
            "sourceTimestamp": row["source_timestamp"],
            "retrievedAt": row["retrieved_at"],
        }
