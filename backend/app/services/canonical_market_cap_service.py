from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_listing_selection_service import (
    CanonicalListingSelectionService,
)
from app.services.country_region_service import CountryRegionService


@dataclass(frozen=True)
class CanonicalMarketCapReport:
    linked_listing_count: int
    canonical_issuer_count: int
    raw_linked_market_cap_usd: float
    canonical_market_cap_usd: float
    duplicate_excess_market_cap_usd: float
    domicile_resolved_issuer_count: int
    domicile_unresolved_issuer_count: int
    domicile_resolved_market_cap_usd: float
    domicile_unresolved_market_cap_usd: float
    region_market_cap_usd: dict[str, float]
    region_weights: dict[str, float]
    multi_listing_issuer_count: int
    cross_listing_ratio_observation_count: int
    median_cross_listing_market_cap_ratio: float | None
    max_cross_listing_market_cap_ratio: float | None
    canonical_listing_market_cap_count: int = 0
    median_fallback_market_cap_count: int = 0

    @property
    def domicile_market_cap_coverage(self) -> float:
        if self.canonical_market_cap_usd <= 0:
            return 0.0
        return self.domicile_resolved_market_cap_usd / self.canonical_market_cap_usd

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "method": "canonical_identity_complete_listing_else_median_cross_listing_market_cap",
            "linkedListingCount": self.linked_listing_count,
            "canonicalIssuerCount": self.canonical_issuer_count,
            "rawLinkedMarketCapUsd": self.raw_linked_market_cap_usd,
            "canonicalMarketCapUsd": self.canonical_market_cap_usd,
            "duplicateExcessMarketCapUsd": self.duplicate_excess_market_cap_usd,
            "domicileResolvedIssuerCount": self.domicile_resolved_issuer_count,
            "domicileUnresolvedIssuerCount": self.domicile_unresolved_issuer_count,
            "domicileResolvedMarketCapUsd": self.domicile_resolved_market_cap_usd,
            "domicileUnresolvedMarketCapUsd": self.domicile_unresolved_market_cap_usd,
            "domicileMarketCapCoverage": self.domicile_market_cap_coverage,
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "regionWeights": dict(self.region_weights),
            "weightsScope": "canonical_issuers_with_resolved_domicile_only",
            "marketCapSelection": {
                "canonicalListingCount": self.canonical_listing_market_cap_count,
                "medianFallbackCount": self.median_fallback_market_cap_count,
                "fallbackMeaning": (
                    "La mediana se conserva sólo como diagnóstico cuando no existe un "
                    "listado doméstico canónico inequívoco con identidad completa y "
                    "capitalización disponible."
                ),
            },
            "crossListingMarketCapConsistency": {
                "multiListingIssuerCount": self.multi_listing_issuer_count,
                "ratioObservationCount": self.cross_listing_ratio_observation_count,
                "medianMaxToMinRatio": self.median_cross_listing_market_cap_ratio,
                "maxMaxToMinRatio": self.max_cross_listing_market_cap_ratio,
                "interpretation": (
                    "Ratios alejados de 1 indican discrepancias entre capitalizaciones "
                    "atribuidas al mismo emisor; son diagnóstico y no habilitan pesos."
                ),
            },
            "excludedKnownNonEquityTypes": ["etf", "fund"],
            "readyForRegionalWeighting": False,
        }


class CanonicalMarketCapService:
    _REGIONS = ("america", "europe", "asia")
    _EXCLUDED_INSTRUMENT_TYPES = ("etf", "fund")

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._identities = IssuerIdentityRepository(database=self._database)
        self._countries = CountryRegionService()
        self._listing_selection = CanonicalListingSelectionService(
            database=self._database
        )

    def get_report(self) -> CanonicalMarketCapReport:
        self._identities.initialize()
        selected_instrument_by_issuer = {
            int(item["issuerId"]): int(item["instrumentId"])
            for item in self._listing_selection.get_report().selections
        }
        excluded_placeholders = ",".join(
            "?" for _ in self._EXCLUDED_INSTRUMENT_TYPES
        )
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    iil.issuer_id,
                    i.id AS instrument_id,
                    i.symbol,
                    i.country AS listing_country,
                    i.is_primary_listing,
                    i.market_cap_usd,
                    ci.domicile_country,
                    ci.region_key
                FROM instrument_issuer_links iil
                JOIN instruments i ON i.id = iil.instrument_id
                JOIN canonical_issuers ci ON ci.id = iil.issuer_id
                WHERE i.is_active = 1
                  AND i.market_cap_usd IS NOT NULL
                  AND i.market_cap_usd > 0
                  AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown')))
                      NOT IN ({excluded_placeholders})
                ORDER BY iil.issuer_id, i.id
                """,
                self._EXCLUDED_INSTRUMENT_TYPES,
            ).fetchall()

        groups: dict[int, dict[str, Any]] = {}
        raw_total = 0.0
        for row in rows:
            issuer_id = int(row["issuer_id"])
            cap = float(row["market_cap_usd"])
            raw_total += cap
            group = groups.setdefault(
                issuer_id,
                {
                    "issuer_id": issuer_id,
                    "listings": [],
                    "domicile_country": row["domicile_country"],
                    "region_key": row["region_key"],
                },
            )
            group["listings"].append(
                {
                    "instrument_id": int(row["instrument_id"]),
                    "symbol": str(row["symbol"]),
                    "listing_country": str(row["listing_country"] or ""),
                    "is_primary_listing": bool(row["is_primary_listing"]),
                    "market_cap_usd": cap,
                }
            )

        canonical_total = 0.0
        resolved_total = 0.0
        unresolved_total = 0.0
        resolved_count = 0
        unresolved_count = 0
        region_caps = {region: 0.0 for region in self._REGIONS}
        cross_listing_ratios: list[float] = []
        multi_listing_issuer_count = 0
        canonical_listing_market_cap_count = 0
        median_fallback_market_cap_count = 0

        for group in groups.values():
            listings = list(group["listings"])
            caps = [float(item["market_cap_usd"]) for item in listings]
            issuer_cap, used_canonical_listing = self._select_issuer_market_cap(
                issuer_id=int(group["issuer_id"]),
                listings=listings,
                selected_instrument_by_issuer=selected_instrument_by_issuer,
            )
            if used_canonical_listing:
                canonical_listing_market_cap_count += 1
            else:
                median_fallback_market_cap_count += 1
            canonical_total += issuer_cap

            if len(caps) > 1:
                multi_listing_issuer_count += 1
                minimum_cap = min(caps)
                maximum_cap = max(caps)
                if minimum_cap > 0:
                    cross_listing_ratios.append(maximum_cap / minimum_cap)

            region = str(group.get("region_key") or "").strip().lower()
            country = str(group.get("domicile_country") or "").strip()

            if country and region in region_caps:
                resolved_count += 1
                resolved_total += issuer_cap
                region_caps[region] += issuer_cap
            else:
                unresolved_count += 1
                unresolved_total += issuer_cap

        region_weights = self._weights_from_caps(region_caps)

        return CanonicalMarketCapReport(
            linked_listing_count=len(rows),
            canonical_issuer_count=len(groups),
            raw_linked_market_cap_usd=raw_total,
            canonical_market_cap_usd=canonical_total,
            duplicate_excess_market_cap_usd=max(0.0, raw_total - canonical_total),
            domicile_resolved_issuer_count=resolved_count,
            domicile_unresolved_issuer_count=unresolved_count,
            domicile_resolved_market_cap_usd=resolved_total,
            domicile_unresolved_market_cap_usd=unresolved_total,
            region_market_cap_usd=region_caps,
            region_weights=region_weights,
            multi_listing_issuer_count=multi_listing_issuer_count,
            cross_listing_ratio_observation_count=len(cross_listing_ratios),
            median_cross_listing_market_cap_ratio=(
                float(median(cross_listing_ratios)) if cross_listing_ratios else None
            ),
            max_cross_listing_market_cap_ratio=(
                max(cross_listing_ratios) if cross_listing_ratios else None
            ),
            canonical_listing_market_cap_count=canonical_listing_market_cap_count,
            median_fallback_market_cap_count=median_fallback_market_cap_count,
        )

    def _select_issuer_market_cap(
        self,
        *,
        issuer_id: int,
        listings: list[dict[str, Any]],
        selected_instrument_by_issuer: dict[int, int],
    ) -> tuple[float, bool]:
        caps = [float(item["market_cap_usd"]) for item in listings]
        selected_instrument_id = selected_instrument_by_issuer.get(issuer_id)
        if selected_instrument_id is not None:
            selected = [
                item
                for item in listings
                if int(item["instrument_id"]) == selected_instrument_id
            ]
            if len(selected) == 1:
                return float(selected[0]["market_cap_usd"]), True

        return float(median(caps)), False

    def _weights_from_caps(self, caps: dict[str, float]) -> dict[str, float]:
        total = sum(caps.values())
        return {
            region: (caps.get(region, 0.0) / total if total > 0 else 0.0)
            for region in self._REGIONS
        }
