from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.canonical_listing_selection_service import CanonicalListingSelectionService
from app.services.canonical_market_cap_service import CanonicalMarketCapService
from app.services.issuer_identity_coverage_service import IssuerIdentityCoverageService


@dataclass(frozen=True)
class MarketWeightingReadinessReport:
    identity_market_cap_coverage: float
    domicile_market_cap_coverage: float
    canonical_issuer_count: int
    region_market_cap_usd: dict[str, float]
    minimum_identity_market_cap_coverage: float
    minimum_domicile_market_cap_coverage: float
    minimum_canonical_issuer_count: int
    external_validation_passed: bool
    external_validation_reference: str | None
    canonical_listing_ambiguous_issuer_count: int = 0
    canonical_listing_market_cap_count: int = 0
    median_fallback_market_cap_count: int = 0

    @property
    def all_regions_represented(self) -> bool:
        return all(
            float(self.region_market_cap_usd.get(region, 0.0)) > 0
            for region in ("america", "europe", "asia")
        )

    @property
    def external_validation_evidence_complete(self) -> bool:
        return self.external_validation_passed and bool(
            str(self.external_validation_reference or "").strip()
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.identity_market_cap_coverage < self.minimum_identity_market_cap_coverage:
            blockers.append("insufficient_canonical_identity_market_cap_coverage")
        if self.domicile_market_cap_coverage < self.minimum_domicile_market_cap_coverage:
            blockers.append("insufficient_issuer_domicile_market_cap_coverage")
        if self.canonical_issuer_count < self.minimum_canonical_issuer_count:
            blockers.append("insufficient_canonical_issuer_count")
        if not self.all_regions_represented:
            blockers.append("required_regions_not_represented")
        if self.canonical_listing_ambiguous_issuer_count > 0:
            blockers.append("ambiguous_canonical_listings_require_resolution")
        if not self.external_validation_evidence_complete:
            blockers.append("external_market_cap_validation_required")
        return tuple(blockers)

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "method": "canonical_domestic_listing_else_median_with_domicile",
            "identityMarketCapCoverage": self.identity_market_cap_coverage,
            "domicileMarketCapCoverage": self.domicile_market_cap_coverage,
            "canonicalIssuerCount": self.canonical_issuer_count,
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "allRegionsRepresented": self.all_regions_represented,
            "canonicalListingValidation": {
                "ambiguousIssuerCount": self.canonical_listing_ambiguous_issuer_count,
                "ambiguityResolved": self.canonical_listing_ambiguous_issuer_count == 0,
            },
            "canonicalMarketCapDiagnostics": {
                "canonicalListingCount": self.canonical_listing_market_cap_count,
                "medianFallbackCount": self.median_fallback_market_cap_count,
                "fallbackIsDiagnosticOnly": True,
            },
            "thresholds": {
                "minimumIdentityMarketCapCoverage": self.minimum_identity_market_cap_coverage,
                "minimumDomicileMarketCapCoverage": self.minimum_domicile_market_cap_coverage,
                "minimumCanonicalIssuerCount": self.minimum_canonical_issuer_count,
            },
            "externalValidation": {
                "passed": self.external_validation_passed,
                "reference": self.external_validation_reference,
                "evidenceComplete": self.external_validation_evidence_complete,
            },
            "blockers": list(self.blockers),
        }


class MarketWeightingReadinessService:
    """Evaluates whether canonical regional market-cap weights may be activated."""

    DEFAULT_MINIMUM_IDENTITY_MARKET_CAP_COVERAGE = 0.95
    DEFAULT_MINIMUM_DOMICILE_MARKET_CAP_COVERAGE = 0.90
    DEFAULT_MINIMUM_CANONICAL_ISSUER_COUNT = 1000

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        minimum_identity_market_cap_coverage: float = DEFAULT_MINIMUM_IDENTITY_MARKET_CAP_COVERAGE,
        minimum_domicile_market_cap_coverage: float = DEFAULT_MINIMUM_DOMICILE_MARKET_CAP_COVERAGE,
        minimum_canonical_issuer_count: int = DEFAULT_MINIMUM_CANONICAL_ISSUER_COUNT,
        external_validation_passed: bool = False,
        external_validation_reference: str | None = None,
    ) -> None:
        if not 0 < minimum_identity_market_cap_coverage <= 1:
            raise ValueError("minimum_identity_market_cap_coverage debe estar entre 0 y 1.")
        if not 0 < minimum_domicile_market_cap_coverage <= 1:
            raise ValueError("minimum_domicile_market_cap_coverage debe estar entre 0 y 1.")
        if minimum_canonical_issuer_count <= 0:
            raise ValueError("minimum_canonical_issuer_count debe ser mayor que 0.")

        self._database = database if database is not None else AthenaDatabase()
        self._minimum_identity_market_cap_coverage = float(minimum_identity_market_cap_coverage)
        self._minimum_domicile_market_cap_coverage = float(minimum_domicile_market_cap_coverage)
        self._minimum_canonical_issuer_count = int(minimum_canonical_issuer_count)
        self._external_validation_passed = bool(external_validation_passed)
        self._external_validation_reference = (
            str(external_validation_reference).strip()
            if external_validation_reference is not None
            and str(external_validation_reference).strip()
            else None
        )

    def get_report(self) -> MarketWeightingReadinessReport:
        identity = IssuerIdentityCoverageService(database=self._database).get_report()
        canonical = CanonicalMarketCapService(database=self._database).get_report()
        canonical_listings = CanonicalListingSelectionService(database=self._database).get_report()

        return MarketWeightingReadinessReport(
            identity_market_cap_coverage=identity.market_cap_coverage,
            domicile_market_cap_coverage=canonical.domicile_market_cap_coverage,
            canonical_issuer_count=canonical.canonical_issuer_count,
            region_market_cap_usd=dict(canonical.region_market_cap_usd),
            minimum_identity_market_cap_coverage=self._minimum_identity_market_cap_coverage,
            minimum_domicile_market_cap_coverage=self._minimum_domicile_market_cap_coverage,
            minimum_canonical_issuer_count=self._minimum_canonical_issuer_count,
            external_validation_passed=self._external_validation_passed,
            external_validation_reference=self._external_validation_reference,
            canonical_listing_ambiguous_issuer_count=canonical_listings.ambiguous_issuer_count,
            canonical_listing_market_cap_count=canonical.canonical_listing_market_cap_count,
            median_fallback_market_cap_count=canonical.median_fallback_market_cap_count,
        )
