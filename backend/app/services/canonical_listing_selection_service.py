from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


@dataclass(frozen=True)
class CanonicalListingSelectionReport:
    eligible_issuer_count: int
    selected_issuer_count: int
    ambiguous_issuer_count: int
    no_domestic_listing_count: int
    selections: tuple[dict[str, Any], ...]
    ambiguous: tuple[dict[str, Any], ...]

    @property
    def selection_coverage(self) -> float:
        if self.eligible_issuer_count <= 0:
            return 0.0
        return self.selected_issuer_count / self.eligible_issuer_count

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "method": "domicile_match_then_explicit_primary",
            "eligibleIssuerCount": self.eligible_issuer_count,
            "selectedIssuerCount": self.selected_issuer_count,
            "ambiguousIssuerCount": self.ambiguous_issuer_count,
            "noDomesticListingCount": self.no_domestic_listing_count,
            "selectionCoverage": self.selection_coverage,
            "selections": [dict(item) for item in self.selections],
            "ambiguous": [dict(item) for item in self.ambiguous],
            "warning": (
                "No se elige un ticker arbitrariamente cuando existen varias clases o "
                "varios listados domésticos sin evidencia explícita de primariedad."
            ),
        }


class CanonicalListingSelectionService:
    _MAX_DIAGNOSTIC_ITEMS = 100

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._identities = IssuerIdentityRepository(database=self._database)

    def get_report(self) -> CanonicalListingSelectionReport:
        self._identities.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ci.id AS issuer_id,
                    ci.canonical_name,
                    ci.domicile_country,
                    i.id AS instrument_id,
                    i.symbol,
                    i.country AS listing_country,
                    i.exchange_short_name,
                    i.is_primary_listing,
                    i.market_cap_usd
                FROM canonical_issuers ci
                JOIN instrument_issuer_links iil ON iil.issuer_id = ci.id
                JOIN instruments i ON i.id = iil.instrument_id
                WHERE ci.domicile_country IS NOT NULL
                  AND TRIM(ci.domicile_country) <> ''
                  AND ci.region_key IS NOT NULL
                  AND TRIM(ci.region_key) <> ''
                  AND i.is_active = 1
                ORDER BY ci.id, i.symbol
                """
            ).fetchall()

        groups: dict[int, dict[str, Any]] = {}
        for row in rows:
            issuer_id = int(row["issuer_id"])
            group = groups.setdefault(
                issuer_id,
                {
                    "issuerId": issuer_id,
                    "canonicalName": str(row["canonical_name"]),
                    "domicileCountry": str(row["domicile_country"]),
                    "listings": [],
                },
            )
            group["listings"].append(
                {
                    "instrumentId": int(row["instrument_id"]),
                    "symbol": str(row["symbol"]),
                    "listingCountry": str(row["listing_country"] or ""),
                    "exchange": str(row["exchange_short_name"] or ""),
                    "isPrimaryListing": bool(row["is_primary_listing"]),
                    "marketCapUsd": row["market_cap_usd"],
                }
            )

        selections: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        no_domestic = 0

        for group in groups.values():
            domicile = self._normalize_country(group["domicileCountry"])
            domestic = [
                listing
                for listing in group["listings"]
                if self._normalize_country(listing["listingCountry"]) == domicile
            ]

            if not domestic:
                no_domestic += 1
                continue

            explicit_primary = [
                listing for listing in domestic if listing["isPrimaryListing"]
            ]

            if len(explicit_primary) == 1:
                selected = explicit_primary[0]
                method = "explicit_primary_domestic_listing"
            elif len(domestic) == 1:
                selected = domestic[0]
                method = "single_domestic_listing"
            else:
                ambiguous.append(
                    {
                        "issuerId": group["issuerId"],
                        "canonicalName": group["canonicalName"],
                        "domicileCountry": group["domicileCountry"],
                        "candidateSymbols": [
                            listing["symbol"] for listing in domestic
                        ],
                        "explicitPrimaryCount": len(explicit_primary),
                    }
                )
                continue

            selections.append(
                {
                    "issuerId": group["issuerId"],
                    "canonicalName": group["canonicalName"],
                    "domicileCountry": group["domicileCountry"],
                    "instrumentId": selected["instrumentId"],
                    "symbol": selected["symbol"],
                    "exchange": selected["exchange"],
                    "selectionMethod": method,
                }
            )

        return CanonicalListingSelectionReport(
            eligible_issuer_count=len(groups),
            selected_issuer_count=len(selections),
            ambiguous_issuer_count=len(ambiguous),
            no_domestic_listing_count=no_domestic,
            selections=tuple(selections[: self._MAX_DIAGNOSTIC_ITEMS]),
            ambiguous=tuple(ambiguous[: self._MAX_DIAGNOSTIC_ITEMS]),
        )

    def _normalize_country(self, value: str) -> str:
        return " ".join(str(value or "").strip().casefold().split())
