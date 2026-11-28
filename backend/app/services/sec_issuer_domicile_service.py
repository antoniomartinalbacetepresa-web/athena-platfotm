from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.country_region_service import CountryRegionService
from app.services.sec_edgar_service import SecEdgarService


class SecSubmissionsProvider(Protocol):
    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class SecIssuerDomicileReport:
    eligible_issuer_count: int
    attempted_issuer_count: int
    resolved_issuer_count: int
    unresolved_issuer_count: int
    failed_issuer_count: int

    @property
    def resolution_rate(self) -> float:
        if self.attempted_issuer_count <= 0:
            return 0.0
        return self.resolved_issuer_count / self.attempted_issuer_count

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "applied_domicile_enrichment",
            "source": "sec_submissions",
            "eligibleIssuerCount": self.eligible_issuer_count,
            "attemptedIssuerCount": self.attempted_issuer_count,
            "resolvedIssuerCount": self.resolved_issuer_count,
            "unresolvedIssuerCount": self.unresolved_issuer_count,
            "failedIssuerCount": self.failed_issuer_count,
            "resolutionRate": self.resolution_rate,
            "warning": (
                "Sólo se persisten domicilios que pueden atribuirse de forma inequívoca "
                "a una región soportada por ATHENA. Jurisdicciones no soportadas o "
                "metadatos ambiguos permanecen sin resolver."
            ),
        }


class SecIssuerDomicileService:
    _SEC_SOURCE = "sec_edgar"
    _SEC_CONFIDENCE = 0.95

    _US_STATE_CODES = frozenset(
        {
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
            "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
            "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
            "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
            "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
            "WY", "X1",
        }
    )
    _CANADA_CODES = frozenset(
        {
            "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
            "B0", "Z4",
            "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE",
            "QC", "SK", "YT",
        }
    )

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        sec_provider: SecSubmissionsProvider | None = None,
        country_region_service: CountryRegionService | None = None,
        identity_repository: IssuerIdentityRepository | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._sec_provider = sec_provider if sec_provider is not None else SecEdgarService()
        self._country_regions = (
            country_region_service
            if country_region_service is not None
            else CountryRegionService()
        )
        self._identities = (
            identity_repository
            if identity_repository is not None
            else IssuerIdentityRepository(database=self._database)
        )

    def apply(self, *, limit: int = 100) -> SecIssuerDomicileReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")

        self._identities.initialize()
        eligible = self._load_unresolved_sec_issuers()
        attempted = eligible[:limit]
        resolved = 0
        unresolved = 0
        failed = 0

        for issuer in attempted:
            try:
                submissions = self._sec_provider.get_submissions(issuer["external_id"])
            except Exception:
                failed += 1
                continue

            domicile = self._resolve_domicile(submissions)
            if domicile is None:
                unresolved += 1
                continue

            country, region = domicile
            self._identities.upsert_external_issuer(
                source_provider=self._SEC_SOURCE,
                external_id=issuer["external_id"],
                canonical_name=issuer["canonical_name"],
                evidence_confidence=self._SEC_CONFIDENCE,
                domicile_country=country,
                region_key=region,
            )
            resolved += 1

        return SecIssuerDomicileReport(
            eligible_issuer_count=len(eligible),
            attempted_issuer_count=len(attempted),
            resolved_issuer_count=resolved,
            unresolved_issuer_count=unresolved,
            failed_issuer_count=failed,
        )

    def _load_unresolved_sec_issuers(self) -> list[dict[str, str]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ci.id,
                    ci.canonical_name,
                    iei.external_id
                FROM canonical_issuers ci
                JOIN issuer_external_ids iei ON iei.issuer_id = ci.id
                WHERE iei.source_provider = ?
                  AND (
                    ci.domicile_country IS NULL
                    OR TRIM(ci.domicile_country) = ''
                    OR ci.region_key IS NULL
                    OR TRIM(ci.region_key) = ''
                  )
                ORDER BY ci.id
                """,
                (self._SEC_SOURCE,),
            ).fetchall()
        return [
            {
                "canonical_name": str(row["canonical_name"]),
                "external_id": str(row["external_id"]),
            }
            for row in rows
        ]

    def _resolve_domicile(self, submissions: dict[str, Any]) -> tuple[str, str] | None:
        code = str(submissions.get("stateOfIncorporation") or "").strip().upper()
        description = str(
            submissions.get("stateOfIncorporationDescription") or ""
        ).strip()

        if code in self._US_STATE_CODES:
            return ("United States", "america")
        if code in self._CANADA_CODES:
            return ("Canada", "america")

        country = self._country_regions.canonical_country_name(description)
        if country is None:
            return None
        region = self._country_regions.region_for_country(country)
        if region is None:
            return None
        return (country, region)
