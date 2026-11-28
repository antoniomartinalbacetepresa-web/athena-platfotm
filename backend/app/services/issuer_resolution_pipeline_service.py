from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.services.canonical_listing_selection_service import (
    CanonicalListingSelectionService,
)
from app.services.canonical_market_cap_service import CanonicalMarketCapService
from app.services.issuer_identity_coverage_service import IssuerIdentityCoverageService
from app.services.sec_edgar_service import SecEdgarService
from app.services.sec_issuer_domicile_service import SecIssuerDomicileService
from app.services.sec_issuer_identity_service import SecIssuerIdentityService


class SecIssuerResolutionProvider(Protocol):
    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        ...

    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class IssuerResolutionPipelineReport:
    identity: dict[str, object]
    domicile: dict[str, object]
    coverage: dict[str, Any]
    canonical_market_cap: dict[str, Any]
    canonical_listing_selection: dict[str, Any]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "issuer_resolution_pipeline_completed",
            "identity": dict(self.identity),
            "domicile": dict(self.domicile),
            "coverage": dict(self.coverage),
            "canonicalMarketCap": dict(self.canonical_market_cap),
            "canonicalListingSelection": dict(self.canonical_listing_selection),
            "isWeightingReady": False,
            "nextGate": "external_market_cap_validation_and_global_identity_coverage",
        }


class IssuerResolutionPipelineService:
    """Runs safe issuer-resolution stages without enabling regional weights."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        sec_provider: SecIssuerResolutionProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._sec_provider = sec_provider if sec_provider is not None else SecEdgarService()

    def run(self, *, domicile_limit: int = 100) -> IssuerResolutionPipelineReport:
        identity = SecIssuerIdentityService(
            database=self._database,
            sec_provider=self._sec_provider,
        ).apply()
        domicile = SecIssuerDomicileService(
            database=self._database,
            sec_provider=self._sec_provider,
        ).apply(limit=domicile_limit)
        coverage = IssuerIdentityCoverageService(
            database=self._database
        ).get_report()
        canonical_market_cap = CanonicalMarketCapService(
            database=self._database
        ).get_report()
        listing_selection = CanonicalListingSelectionService(
            database=self._database
        ).get_report()

        return IssuerResolutionPipelineReport(
            identity=identity.to_api_dict(),
            domicile=domicile.to_api_dict(),
            coverage=coverage.to_api_dict(),
            canonical_market_cap=canonical_market_cap.to_api_dict(),
            canonical_listing_selection=listing_selection.to_api_dict(),
        )
