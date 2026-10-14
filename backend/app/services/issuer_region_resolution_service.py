from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.yahoo_instrument_metadata_service import (
    YahooInstrumentMetadataService,
)


class InstrumentMetadataProvider(Protocol):
    def get_metadata(self, symbol: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class IssuerRegionResolutionReport:
    cross_region_group_count: int
    attempted_group_count: int
    resolved_group_count: int
    unresolved_group_count: int
    resolved_market_cap_usd: float
    unresolved_market_cap_usd: float
    region_market_cap_usd: dict[str, float]
    region_weights: dict[str, float]
    resolved_groups: tuple[dict[str, Any], ...]
    unresolved_groups: tuple[dict[str, Any], ...]

    @property
    def resolution_coverage(self) -> float:
        total = self.resolved_market_cap_usd + self.unresolved_market_cap_usd
        return self.resolved_market_cap_usd / total if total > 0 else 0.0

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "method": "yahoo_issuer_country_for_cross_region_name_groups",
            "warning": (
                "La agrupación por nombre normalizado sigue siendo heurística. "
                "La región sólo se considera resuelta cuando Yahoo devuelve un país "
                "de emisor soportado y las consultas válidas del grupo no discrepan."
            ),
            "crossRegionGroupCount": self.cross_region_group_count,
            "attemptedGroupCount": self.attempted_group_count,
            "resolvedGroupCount": self.resolved_group_count,
            "unresolvedGroupCount": self.unresolved_group_count,
            "resolvedMarketCapUsd": self.resolved_market_cap_usd,
            "unresolvedMarketCapUsd": self.unresolved_market_cap_usd,
            "resolutionCoverage": self.resolution_coverage,
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "regionWeights": dict(self.region_weights),
            "resolvedGroups": [dict(group) for group in self.resolved_groups],
            "unresolvedGroups": [dict(group) for group in self.unresolved_groups],
        }


class IssuerRegionResolutionService:
    """Resuelve domicilio regional de emisores que aparecen en varias regiones.

    Esta capa es deliberadamente diagnóstica. No persiste identidades de emisor
    ni activa pesos de producción. Reduce el universo de consultas a los grupos
    con conflicto regional y conserva como no resuelto cualquier discrepancia.
    """

    _REGIONS = ("america", "europe", "asia")
    _MAX_METADATA_ATTEMPTS_PER_GROUP = 3

    _AMERICA_COUNTRIES = frozenset(
        {
            "argentina",
            "brazil",
            "canada",
            "chile",
            "colombia",
            "mexico",
            "peru",
            "united states",
            "united states of america",
        }
    )
    _EUROPE_COUNTRIES = frozenset(
        {
            "austria",
            "belgium",
            "denmark",
            "finland",
            "france",
            "germany",
            "ireland",
            "italy",
            "netherlands",
            "norway",
            "poland",
            "portugal",
            "spain",
            "sweden",
            "switzerland",
            "united kingdom",
        }
    )
    _ASIA_COUNTRIES = frozenset(
        {
            "china",
            "hong kong",
            "india",
            "indonesia",
            "japan",
            "malaysia",
            "philippines",
            "singapore",
            "south korea",
            "taiwan",
            "thailand",
            "vietnam",
        }
    )

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        metadata_provider: InstrumentMetadataProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)
        self._metadata_provider = (
            metadata_provider
            if metadata_provider is not None
            else YahooInstrumentMetadataService()
        )

    def get_report(self, *, max_groups: int | None = None) -> IssuerRegionResolutionReport:
        if max_groups is not None and max_groups <= 0:
            raise ValueError("max_groups debe ser mayor que 0 o None.")

        self._database.initialize()
        rows = self._repository.list_active()
        groups = self._build_cross_region_groups(rows)
        groups.sort(
            key=lambda group: float(group["representativeMarketCapUsd"]),
            reverse=True,
        )

        selected = groups if max_groups is None else groups[:max_groups]
        resolved: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        region_market_cap = {region: 0.0 for region in self._REGIONS}

        for group in selected:
            result = self._resolve_group(group)
            if result["status"] == "resolved":
                resolved.append(result)
                region_market_cap[str(result["issuerRegionKey"])] += float(
                    result["representativeMarketCapUsd"]
                )
            else:
                unresolved.append(result)

        resolved_market_cap = sum(
            float(group["representativeMarketCapUsd"]) for group in resolved
        )
        unresolved_market_cap = sum(
            float(group["representativeMarketCapUsd"]) for group in unresolved
        )
        resolved_total = sum(region_market_cap.values())
        region_weights = {
            region: (
                region_market_cap[region] / resolved_total
                if resolved_total > 0
                else 0.0
            )
            for region in self._REGIONS
        }

        return IssuerRegionResolutionReport(
            cross_region_group_count=len(groups),
            attempted_group_count=len(selected),
            resolved_group_count=len(resolved),
            unresolved_group_count=len(unresolved),
            resolved_market_cap_usd=resolved_market_cap,
            unresolved_market_cap_usd=unresolved_market_cap,
            region_market_cap_usd=region_market_cap,
            region_weights=region_weights,
            resolved_groups=tuple(resolved),
            unresolved_groups=tuple(unresolved),
        )

    def _build_cross_region_groups(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            cap = row.get("market_cap_usd")
            region = str(row.get("region_key") or "").strip().lower()
            name = str(row.get("company_name") or "").strip()
            symbol = str(row.get("symbol") or "").strip().upper()
            if (
                not isinstance(cap, (int, float))
                or cap <= 0
                or region not in self._REGIONS
                or not name
                or not symbol
            ):
                continue
            key = self._normalize_name(name)
            grouped.setdefault(key, []).append(
                {
                    "symbol": symbol,
                    "companyName": name,
                    "listingCountry": str(row.get("country") or "").strip(),
                    "listingRegionKey": region,
                    "marketCapUsd": float(cap),
                }
            )

        result: list[dict[str, Any]] = []
        for assets in grouped.values():
            regions = sorted({str(asset["listingRegionKey"]) for asset in assets})
            if len(regions) <= 1:
                continue
            caps = [float(asset["marketCapUsd"]) for asset in assets]
            representative_cap = float(median(caps))
            candidates = sorted(
                assets,
                key=lambda asset: abs(
                    float(asset["marketCapUsd"]) - representative_cap
                ),
            )
            result.append(
                {
                    "companyName": candidates[0]["companyName"],
                    "listingCount": len(assets),
                    "listingRegions": regions,
                    "representativeMarketCapUsd": representative_cap,
                    "candidateSymbols": [
                        str(asset["symbol"]) for asset in candidates
                    ],
                }
            )
        return result

    def _resolve_group(self, group: dict[str, Any]) -> dict[str, Any]:
        successful: list[dict[str, str]] = []
        errors: list[str] = []

        for symbol in group["candidateSymbols"][
            : self._MAX_METADATA_ATTEMPTS_PER_GROUP
        ]:
            try:
                metadata = self._metadata_provider.get_metadata(str(symbol))
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}")
                continue

            country = str(metadata.get("country") or "").strip()
            region = self._region_for_country(country)
            if not country or region is None:
                errors.append(f"{symbol}: unsupported_country={country or 'missing'}")
                continue
            successful.append(
                {
                    "symbol": str(symbol),
                    "country": country,
                    "regionKey": region,
                }
            )

        region_keys = {item["regionKey"] for item in successful}
        countries = {item["country"] for item in successful}
        base = {
            "companyName": group["companyName"],
            "listingCount": group["listingCount"],
            "listingRegions": list(group["listingRegions"]),
            "representativeMarketCapUsd": group["representativeMarketCapUsd"],
            "metadataObservations": successful,
            "errors": errors,
        }

        if not successful:
            return {
                **base,
                "status": "unresolved",
                "reason": "no_supported_issuer_country",
            }
        if len(region_keys) != 1:
            return {
                **base,
                "status": "unresolved",
                "reason": "conflicting_issuer_regions",
            }

        issuer_region = next(iter(region_keys))
        issuer_country = sorted(countries)[0] if len(countries) == 1 else None
        return {
            **base,
            "status": "resolved",
            "issuerCountry": issuer_country,
            "issuerRegionKey": issuer_region,
            "countryAgreement": len(countries) == 1,
        }

    def _region_for_country(self, country: str) -> str | None:
        normalized = " ".join(country.casefold().split())
        if normalized in self._AMERICA_COUNTRIES:
            return "america"
        if normalized in self._EUROPE_COUNTRIES:
            return "europe"
        if normalized in self._ASIA_COUNTRIES:
            return "asia"
        return None

    def _normalize_name(self, value: str) -> str:
        return " ".join(value.casefold().split())
