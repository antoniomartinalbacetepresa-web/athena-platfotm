from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.sec_edgar_service import SecEdgarService


class SecTickerAssociationProvider(Protocol):
    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class SecIssuerIdentityReport:
    eligible_listing_count: int
    linked_listing_count: int
    ambiguous_listing_count: int
    unmatched_listing_count: int
    unique_issuer_count: int

    @property
    def coverage(self) -> float:
        if self.eligible_listing_count <= 0:
            return 0.0
        return self.linked_listing_count / self.eligible_listing_count

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "applied_identity_only",
            "source": "sec_company_tickers_exchange",
            "resolutionMethod": "exact_ticker_unique_cik",
            "identityConfidence": 0.95,
            "eligibleListingCount": self.eligible_listing_count,
            "linkedListingCount": self.linked_listing_count,
            "ambiguousListingCount": self.ambiguous_listing_count,
            "unmatchedListingCount": self.unmatched_listing_count,
            "uniqueIssuerCount": self.unique_issuer_count,
            "coverage": self.coverage,
            "domicileResolved": False,
            "warning": (
                "SEC CIK se usa aquí sólo como evidencia fuerte de identidad de emisor. "
                "No se infiere domicilio ni región del emisor a partir del mercado de "
                "cotización."
            ),
        }


class SecIssuerIdentityService:
    """Links persisted US-venue listings to canonical issuers via SEC CIK."""

    _IDENTITY_CONFIDENCE = 0.95
    _SOURCE_PROVIDER = "sec_edgar"
    _EVIDENCE_SOURCE = "sec_company_tickers_exchange"
    _RESOLUTION_METHOD = "exact_ticker_unique_cik"

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        sec_provider: SecTickerAssociationProvider | None = None,
        identity_repository: IssuerIdentityRepository | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._instrument_repository = InstrumentRepository(database=self._database)
        self._identity_repository = (
            identity_repository
            if identity_repository is not None
            else IssuerIdentityRepository(database=self._database)
        )
        self._sec_provider = (
            sec_provider if sec_provider is not None else SecEdgarService()
        )

    def apply(self) -> SecIssuerIdentityReport:
        self._database.initialize()
        rows = [
            row
            for row in self._instrument_repository.list_active()
            if self._is_eligible_us_listing(row)
        ]
        associations = self._sec_provider.get_company_ticker_exchange_associations()

        by_ticker: dict[str, dict[str, dict[str, str]]] = {}
        for association in associations:
            ticker = str(association.get("ticker") or "").strip().upper()
            cik = str(association.get("cik") or "").strip()
            name = str(association.get("name") or "").strip()
            if not ticker or not cik or not name:
                continue
            by_ticker.setdefault(ticker, {})[cik] = association

        linked = 0
        ambiguous = 0
        unmatched = 0
        issuer_ids: set[int] = set()

        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            candidates = list(by_ticker.get(symbol, {}).values())
            if not candidates:
                unmatched += 1
                continue
            if len(candidates) != 1:
                ambiguous += 1
                continue

            candidate = candidates[0]
            issuer_id = self._identity_repository.upsert_external_issuer(
                source_provider=self._SOURCE_PROVIDER,
                external_id=str(candidate["cik"]),
                canonical_name=str(candidate["name"]),
                evidence_confidence=self._IDENTITY_CONFIDENCE,
            )
            self._identity_repository.link_instrument(
                instrument_id=int(row["id"]),
                issuer_id=issuer_id,
                evidence_source=self._EVIDENCE_SOURCE,
                resolution_method=self._RESOLUTION_METHOD,
                confidence=self._IDENTITY_CONFIDENCE,
            )
            linked += 1
            issuer_ids.add(issuer_id)

        return SecIssuerIdentityReport(
            eligible_listing_count=len(rows),
            linked_listing_count=linked,
            ambiguous_listing_count=ambiguous,
            unmatched_listing_count=unmatched,
            unique_issuer_count=len(issuer_ids),
        )

    def _is_eligible_us_listing(self, row: dict[str, object]) -> bool:
        country = str(row.get("country") or "").strip().casefold()
        symbol = str(row.get("symbol") or "").strip()
        return country in {"united states", "united states of america"} and bool(symbol)
