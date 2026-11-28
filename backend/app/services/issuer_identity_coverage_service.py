from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


@dataclass(frozen=True)
class IssuerIdentityCoverageReport:
    eligible_listing_count: int
    linked_listing_count: int
    eligible_market_cap_usd: float
    linked_market_cap_usd: float
    unique_linked_issuer_count: int
    high_confidence_linked_listing_count: int
    domicile_resolved_issuer_count: int
    domicile_unresolved_issuer_count: int

    @property
    def listing_coverage(self) -> float:
        if self.eligible_listing_count <= 0:
            return 0.0
        return self.linked_listing_count / self.eligible_listing_count

    @property
    def market_cap_coverage(self) -> float:
        if self.eligible_market_cap_usd <= 0:
            return 0.0
        return self.linked_market_cap_usd / self.eligible_market_cap_usd

    @property
    def domicile_coverage(self) -> float:
        total = self.domicile_resolved_issuer_count + self.domicile_unresolved_issuer_count
        if total <= 0:
            return 0.0
        return self.domicile_resolved_issuer_count / total

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "identityLayer": "canonical_issuers",
            "eligibleListingCount": self.eligible_listing_count,
            "linkedListingCount": self.linked_listing_count,
            "listingCoverage": self.listing_coverage,
            "eligibleMarketCapUsd": self.eligible_market_cap_usd,
            "linkedMarketCapUsd": self.linked_market_cap_usd,
            "marketCapCoverage": self.market_cap_coverage,
            "uniqueLinkedIssuerCount": self.unique_linked_issuer_count,
            "highConfidenceLinkedListingCount": (
                self.high_confidence_linked_listing_count
            ),
            "domicileResolvedIssuerCount": self.domicile_resolved_issuer_count,
            "domicileUnresolvedIssuerCount": self.domicile_unresolved_issuer_count,
            "domicileCoverage": self.domicile_coverage,
            "readyForRegionalWeighting": False,
            "warning": (
                "La identidad canónica y el domicilio son dimensiones separadas. "
                "Una cobertura alta de identidad no habilita pesos regionales hasta "
                "resolver y validar el domicilio del emisor."
            ),
        }


class IssuerIdentityCoverageService:
    _HIGH_CONFIDENCE_THRESHOLD = 0.9

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._identity_repository = IssuerIdentityRepository(database=self._database)

    def get_report(self) -> IssuerIdentityCoverageReport:
        self._identity_repository.initialize()

        with self._database.connect() as connection:
            eligible = connection.execute(
                """
                SELECT
                    COUNT(*) AS listing_count,
                    COALESCE(SUM(market_cap_usd), 0) AS market_cap_usd
                FROM instruments
                WHERE is_active = 1
                  AND market_cap_usd IS NOT NULL
                  AND market_cap_usd > 0
                """
            ).fetchone()

            linked = connection.execute(
                """
                SELECT
                    COUNT(*) AS listing_count,
                    COALESCE(SUM(i.market_cap_usd), 0) AS market_cap_usd,
                    COUNT(DISTINCT iil.issuer_id) AS issuer_count,
                    SUM(
                        CASE
                            WHEN iil.confidence >= ? THEN 1
                            ELSE 0
                        END
                    ) AS high_confidence_count
                FROM instrument_issuer_links iil
                JOIN instruments i ON i.id = iil.instrument_id
                WHERE i.is_active = 1
                  AND i.market_cap_usd IS NOT NULL
                  AND i.market_cap_usd > 0
                """,
                (self._HIGH_CONFIDENCE_THRESHOLD,),
            ).fetchone()

            domicile = connection.execute(
                """
                SELECT
                    SUM(
                        CASE
                            WHEN domicile_country IS NOT NULL
                             AND TRIM(domicile_country) <> ''
                             AND region_key IS NOT NULL
                             AND TRIM(region_key) <> ''
                            THEN 1 ELSE 0
                        END
                    ) AS resolved_count,
                    SUM(
                        CASE
                            WHEN domicile_country IS NULL
                              OR TRIM(COALESCE(domicile_country, '')) = ''
                              OR region_key IS NULL
                              OR TRIM(COALESCE(region_key, '')) = ''
                            THEN 1 ELSE 0
                        END
                    ) AS unresolved_count
                FROM canonical_issuers
                WHERE id IN (
                    SELECT DISTINCT issuer_id
                    FROM instrument_issuer_links
                )
                """
            ).fetchone()

        return IssuerIdentityCoverageReport(
            eligible_listing_count=int(eligible["listing_count"] if eligible else 0),
            linked_listing_count=int(linked["listing_count"] if linked else 0),
            eligible_market_cap_usd=float(eligible["market_cap_usd"] if eligible else 0),
            linked_market_cap_usd=float(linked["market_cap_usd"] if linked else 0),
            unique_linked_issuer_count=int(linked["issuer_count"] if linked else 0),
            high_confidence_linked_listing_count=int(
                linked["high_confidence_count"] if linked and linked["high_confidence_count"] else 0
            ),
            domicile_resolved_issuer_count=int(
                domicile["resolved_count"] if domicile and domicile["resolved_count"] else 0
            ),
            domicile_unresolved_issuer_count=int(
                domicile["unresolved_count"] if domicile and domicile["unresolved_count"] else 0
            ),
        )
