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
    minimum_global_usable_count: int
    minimum_usable_per_region: int
    minimum_usable_coverage: float
    is_global_ready: bool
    using_fallback: bool

    @property
    def usable_coverage(self) -> float:
        return (
            self.globally_usable_count / self.active_count
            if self.active_count > 0
            else 0.0
        )

    @property
    def is_weighting_ready(self) -> bool:
        # El universo persistido actual se descubre con una cuota fija de
        # resultados por país (top-N por capitalización). Esa estrategia es
        # válida para construir catálogo y cobertura, pero no para inferir
        # directamente el peso bursátil relativo de continentes: regiones con
        # más países configurados quedarían sobrerrepresentadas.
        #
        # Se mantendrá False hasta sustituir esta selección por una metodología
        # comparable entre regiones (por ejemplo, umbral global uniforme o
        # cobertura acumulada de capitalización suficientemente completa).
        return False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "activeCount": self.active_count,
            "marketCapReadyCount": self.market_cap_ready_count,
            "countryReadyCount": self.country_ready_count,
            "globallyUsableCount": self.globally_usable_count,
            "usableCoverage": self.usable_coverage,
            "regionCounts": dict(self.region_counts),
            "representedRegions": list(self.represented_regions),
            "requiredRegions": ["america", "europe", "asia"],
            "minimumGlobalUsableCount": self.minimum_global_usable_count,
            "minimumUsablePerRegion": self.minimum_usable_per_region,
            "minimumUsableCoverage": self.minimum_usable_coverage,
            "coverageGateEnabled": False,
            "isGlobalReady": self.is_global_ready,
            "usingFallback": self.using_fallback,
            "isWeightingReady": self.is_weighting_ready,
            "weightingMethod": "country_top_n_market_cap",
            "weightingStatus": "calibration_required",
        }


class PersistedMarketUniverseService:
    """Sirve sólo activos persistidos aptos para análisis de cobertura global."""

    DEFAULT_MINIMUM_GLOBAL_USABLE_COUNT = 100
    DEFAULT_MINIMUM_USABLE_PER_REGION = 20
    DEFAULT_MINIMUM_USABLE_COVERAGE = 0.30

    _REQUIRED_REGIONS = frozenset({"america", "europe", "asia"})
    _REGION_ORDER = ("america", "europe", "asia")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        fallback_service: MarketUniverseFallback | None = None,
        minimum_global_usable_count: int = DEFAULT_MINIMUM_GLOBAL_USABLE_COUNT,
        minimum_usable_per_region: int = DEFAULT_MINIMUM_USABLE_PER_REGION,
        minimum_usable_coverage: float = DEFAULT_MINIMUM_USABLE_COVERAGE,
    ) -> None:
        if minimum_global_usable_count <= 0:
            raise ValueError("minimum_global_usable_count debe ser mayor que 0.")
        if minimum_usable_per_region <= 0:
            raise ValueError("minimum_usable_per_region debe ser mayor que 0.")
        if not 0 < minimum_usable_coverage <= 1:
            raise ValueError("minimum_usable_coverage debe estar entre 0 y 1.")

        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)
        self._fallback_service = (
            fallback_service
            if fallback_service is not None
            else YahooMarketUniverseService()
        )
        self._minimum_global_usable_count = int(minimum_global_usable_count)
        self._minimum_usable_per_region = int(minimum_usable_per_region)
        self._minimum_usable_coverage = float(minimum_usable_coverage)

    def get_universe(self) -> list[dict[str, Any]]:
        rows = self._load_active_rows()
        usable_rows = [row for row in rows if self._is_globally_usable(row)]
        report = self._build_quality_report(rows)

        if not report.is_global_ready:
            return self._fallback_service.get_universe()

        return [self._to_api_asset(row) for row in usable_rows]

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
        regions_have_depth = all(
            region_counts[region] >= self._minimum_usable_per_region
            for region in self._REGION_ORDER
        )

        # El catálogo persistido puede contener miles de instrumentos de
        # identidad todavía no enriquecidos. La densidad de enriquecimiento
        # se conserva como diagnóstico, pero no bloquea la activación del
        # catálogo real. La aptitud para calcular pesos regionales se evalúa
        # separadamente mediante is_weighting_ready.
        is_global_ready = (
            globally_usable_count >= self._minimum_global_usable_count
            and regions_have_depth
        )

        return MarketUniverseQualityReport(
            active_count=len(rows),
            market_cap_ready_count=market_cap_ready_count,
            country_ready_count=country_ready_count,
            globally_usable_count=globally_usable_count,
            region_counts=region_counts,
            represented_regions=represented_regions,
            minimum_global_usable_count=self._minimum_global_usable_count,
            minimum_usable_per_region=self._minimum_usable_per_region,
            minimum_usable_coverage=self._minimum_usable_coverage,
            is_global_ready=is_global_ready,
            using_fallback=not is_global_ready,
        )

    def _is_globally_usable(self, row: dict[str, Any]) -> bool:
        market_cap = row.get("market_cap_usd")
        if not isinstance(market_cap, (int, float)) or market_cap <= 0:
            return False

        country = str(row.get("country") or "").strip()
        if not country:
            return False

        region_key = str(row.get("region_key") or "").strip().lower()
        return region_key in self._REQUIRED_REGIONS

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
