from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


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

    @property
    def domicile_market_cap_coverage(self) -> float:
        if self.canonical_market_cap_usd <= 0:
            return 0.0
        return self.domicile_resolved_market_cap_usd / self.canonical_market_cap_usd

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "method": "canonical_issuer_median_cross_listing_market_cap",
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
            "readyForRegionalWeighting": False,
        }


class CanonicalMarketCapService:
    _REGIONS = ("america", "europe", "asia")

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._identities = IssuerIdentityRepository(database=self._database)

    def get_report(self) -> CanonicalMarketCapReport:
        self._identities.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    iil.issuer_id,
                    i.market_cap_usd,
                    ci.domicile_country,
                    ci.region_key
                FROM instrument_issuer_links iil
                JOIN instruments i ON i.id = iil.instrument_id
                JOIN canonical_issuers ci ON ci.id = iil.issuer_id
                WHERE i.is_active = 1
                  AND i.market_cap_usd IS NOT NULL
                  AND i.market_cap_usd > 0
                ORDER BY iil.issuer_id
                """
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
                    "caps": [],
                    "domicile_country": row["domicile_country"],
                    "region_key": row["region_key"],
                },
            )
            group["caps"].append(cap)

        canonical_total = 0.0
        resolved_total = 0.0
        unresolved_total = 0.0
        resolved_count = 0
        unresolved_count = 0
        region_caps = {region: 0.0 for region in self._REGIONS}

        for group in groups.values():
            issuer_cap = float(median(group["caps"]))
            canonical_total += issuer_cap
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
        )

    def _weights_from_caps(self, caps: dict[str, float]) -> dict[str, float]:
        total = sum(caps.values())
        return {
            region: (caps.get(region, 0.0) / total if total > 0 else 0.0)
            for region in self._REGIONS
        }
