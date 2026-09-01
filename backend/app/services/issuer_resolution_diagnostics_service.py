from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository


@dataclass(frozen=True)
class IssuerResolutionDiagnosticsReport:
    usable_listing_count: int
    listings_with_issuer_id_count: int
    explicit_issuer_count: int
    canonical_explicit_issuer_count: int
    primary_listing_count: int
    issuer_groups_without_primary_listing_count: int
    issuer_groups_with_multiple_primary_listings_count: int
    cross_region_issuer_group_count: int
    canonical_market_cap_usd: float
    canonical_region_market_cap_usd: dict[str, float]
    canonical_region_weights: dict[str, float]
    top_ambiguous_issuer_groups: tuple[dict[str, Any], ...]

    @property
    def issuer_id_listing_coverage(self) -> float:
        if self.usable_listing_count <= 0:
            return 0.0
        return self.listings_with_issuer_id_count / self.usable_listing_count

    @property
    def unresolved_listing_count(self) -> int:
        return max(
            0,
            self.usable_listing_count - self.listings_with_issuer_id_count,
        )

    @property
    def has_sufficient_identity_for_weighting(self) -> bool:
        # Conservative diagnostic only. Production activation must additionally
        # validate issuer identifiers and regional totals against external
        # reference data.
        return (
            self.usable_listing_count > 0
            and self.issuer_id_listing_coverage >= 0.95
            and self.issuer_groups_with_multiple_primary_listings_count == 0
            and self.issuer_groups_without_primary_listing_count == 0
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "usableListingCount": self.usable_listing_count,
            "listingsWithIssuerIdCount": self.listings_with_issuer_id_count,
            "issuerIdListingCoverage": self.issuer_id_listing_coverage,
            "unresolvedListingCount": self.unresolved_listing_count,
            "explicitIssuerCount": self.explicit_issuer_count,
            "canonicalExplicitIssuerCount": self.canonical_explicit_issuer_count,
            "primaryListingCount": self.primary_listing_count,
            "issuerGroupsWithoutPrimaryListingCount": (
                self.issuer_groups_without_primary_listing_count
            ),
            "issuerGroupsWithMultiplePrimaryListingsCount": (
                self.issuer_groups_with_multiple_primary_listings_count
            ),
            "crossRegionIssuerGroupCount": self.cross_region_issuer_group_count,
            "canonicalMarketCapUsd": self.canonical_market_cap_usd,
            "canonicalRegionMarketCapUsd": dict(
                self.canonical_region_market_cap_usd
            ),
            "canonicalRegionWeights": dict(self.canonical_region_weights),
            "hasSufficientIdentityForWeighting": (
                self.has_sufficient_identity_for_weighting
            ),
            "topAmbiguousIssuerGroups": [
                dict(group) for group in self.top_ambiguous_issuer_groups
            ],
        }


class IssuerResolutionDiagnosticsService:
    """Measures how close the persisted universe is to issuer-safe weighting.

    Only explicit ``issuer_id`` values are treated as issuer identity. Company
    names are deliberately not used here because they are not reliable legal
    identifiers. Canonical market-cap totals therefore include only listings
    whose issuer identity is explicitly known.
    """

    _REGIONS = ("america", "europe", "asia")
    _TOP_AMBIGUOUS_GROUPS = 50

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)

    def get_report(self) -> IssuerResolutionDiagnosticsReport:
        self._database.initialize()
        usable = [
            row
            for row in self._repository.list_active()
            if self._is_globally_usable(row)
        ]

        primary_listing_count = sum(
            1 for row in usable if bool(row.get("is_primary_listing"))
        )
        explicit_rows = [
            row
            for row in usable
            if str(row.get("issuer_id") or "").strip()
        ]

        groups: dict[str, list[dict[str, Any]]] = {}
        for row in explicit_rows:
            issuer_id = str(row["issuer_id"]).strip()
            groups.setdefault(issuer_id, []).append(row)

        canonical_region_caps = {region: 0.0 for region in self._REGIONS}
        canonical_total = 0.0
        missing_primary = 0
        multiple_primary = 0
        cross_region = 0
        ambiguous_groups: list[dict[str, Any]] = []

        for issuer_id, rows in groups.items():
            primaries = [
                row for row in rows if bool(row.get("is_primary_listing"))
            ]
            regions = sorted(
                {
                    str(row.get("region_key") or "").strip().lower()
                    for row in rows
                    if str(row.get("region_key") or "").strip().lower()
                    in self._REGIONS
                }
            )
            if len(regions) > 1:
                cross_region += 1

            selection_status: str
            if len(primaries) == 1:
                representative = primaries[0]
                selection_status = "explicit_primary"
            elif len(primaries) == 0:
                missing_primary += 1
                representative = max(
                    rows,
                    key=lambda row: float(row["market_cap_usd"]),
                )
                selection_status = "fallback_largest_market_cap"
            else:
                multiple_primary += 1
                representative = max(
                    primaries,
                    key=lambda row: float(row["market_cap_usd"]),
                )
                selection_status = "multiple_primary_fallback_largest"

            cap = float(representative["market_cap_usd"])
            region = str(representative["region_key"]).strip().lower()
            canonical_total += cap
            canonical_region_caps[region] += cap

            if selection_status != "explicit_primary":
                ambiguous_groups.append(
                    {
                        "issuerId": issuer_id,
                        "listingCount": len(rows),
                        "primaryListingCount": len(primaries),
                        "selectionStatus": selection_status,
                        "representativeSymbol": str(
                            representative.get("symbol") or ""
                        ),
                        "representativeCompanyName": str(
                            representative.get("company_name") or ""
                        ),
                        "representativeRegionKey": region,
                        "representativeMarketCapUsd": cap,
                        "regions": regions,
                        "symbols": [
                            str(row.get("symbol") or "")
                            for row in sorted(
                                rows,
                                key=lambda item: float(item["market_cap_usd"]),
                                reverse=True,
                            )[:20]
                        ],
                    }
                )

        ambiguous_groups.sort(
            key=lambda group: float(group["representativeMarketCapUsd"]),
            reverse=True,
        )

        return IssuerResolutionDiagnosticsReport(
            usable_listing_count=len(usable),
            listings_with_issuer_id_count=len(explicit_rows),
            explicit_issuer_count=len(groups),
            canonical_explicit_issuer_count=len(groups),
            primary_listing_count=primary_listing_count,
            issuer_groups_without_primary_listing_count=missing_primary,
            issuer_groups_with_multiple_primary_listings_count=multiple_primary,
            cross_region_issuer_group_count=cross_region,
            canonical_market_cap_usd=canonical_total,
            canonical_region_market_cap_usd=canonical_region_caps,
            canonical_region_weights=self._weights(canonical_region_caps),
            top_ambiguous_issuer_groups=tuple(
                ambiguous_groups[: self._TOP_AMBIGUOUS_GROUPS]
            ),
        )

    def _is_globally_usable(self, row: dict[str, Any]) -> bool:
        cap = row.get("market_cap_usd")
        if not isinstance(cap, (int, float)) or cap <= 0:
            return False

        country = str(row.get("country") or "").strip()
        if not country:
            return False

        region = str(row.get("region_key") or "").strip().lower()
        return region in self._REGIONS

    def _weights(self, caps: dict[str, float]) -> dict[str, float]:
        total = sum(caps.values())
        return {
            region: (caps.get(region, 0.0) / total if total > 0 else 0.0)
            for region in self._REGIONS
        }
