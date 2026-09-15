from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.market_weighting_external_validation_repository import MarketWeightingExternalValidationRepository
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
    canonical_listing_no_domestic_issuer_count: int = 0
    canonical_listing_market_cap_count: int = 0
    median_fallback_market_cap_count: int = 0
    identity_evidence_fingerprint: str | None = None
    external_validation_fingerprint: str | None = None

    @property
    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not isfinite(self.identity_market_cap_coverage) or self.identity_market_cap_coverage < self.minimum_identity_market_cap_coverage:
            blockers.append("insufficient_issuer_identity_market_cap_coverage")
        if not isfinite(self.domicile_market_cap_coverage) or self.domicile_market_cap_coverage < self.minimum_domicile_market_cap_coverage:
            blockers.append("insufficient_issuer_domicile_market_cap_coverage")
        if self.canonical_issuer_count < self.minimum_canonical_issuer_count:
            blockers.append("insufficient_canonical_issuer_count")
        required_regions = {"america", "europe", "asia"}
        represented_regions = {
            region
            for region, market_cap in self.region_market_cap_usd.items()
            if isfinite(float(market_cap)) and float(market_cap) > 0
        }
        if not required_regions.issubset(represented_regions):
            blockers.append("required_regions_not_represented")
        if self.canonical_listing_ambiguous_issuer_count > 0:
            blockers.append("ambiguous_canonical_listings_require_resolution")
        if self.canonical_listing_no_domestic_issuer_count > 0:
            blockers.append("canonical_listings_without_domestic_match_require_resolution")
        if self.median_fallback_market_cap_count > 0:
            blockers.append("median_fallback_market_caps_require_resolution")
        if not self.external_validation_passed:
            blockers.append("external_market_cap_validation_required")
        return blockers

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.ready else "blocked",
            "ready": self.ready,
            "method": "canonical_domestic_listing_else_median_with_domicile",
            "identityMarketCapCoverage": self.identity_market_cap_coverage,
            "domicileMarketCapCoverage": self.domicile_market_cap_coverage,
            "canonicalIssuerCount": self.canonical_issuer_count,
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "minimumIdentityMarketCapCoverage": self.minimum_identity_market_cap_coverage,
            "minimumDomicileMarketCapCoverage": self.minimum_domicile_market_cap_coverage,
            "minimumCanonicalIssuerCount": self.minimum_canonical_issuer_count,
            "canonicalMarketCapDiagnostics": {
                "canonicalListingCount": self.canonical_listing_market_cap_count,
                "medianFallbackCount": self.median_fallback_market_cap_count,
                "fallbackIsDiagnosticOnly": True,
                "fallbackResolvedForActivation": self.median_fallback_market_cap_count == 0,
            },
            "canonicalListingValidation": {
                "ambiguousIssuerCount": self.canonical_listing_ambiguous_issuer_count,
                "noDomesticListingCount": self.canonical_listing_no_domestic_issuer_count,
                "domesticListingCoverageComplete": (
                    self.canonical_listing_ambiguous_issuer_count == 0
                    and self.canonical_listing_no_domestic_issuer_count == 0
                ),
            },
            "identityEvidenceFingerprint": self.identity_evidence_fingerprint,
            "externalValidation": {
                "passed": self.external_validation_passed,
                "reference": self.external_validation_reference,
                "validationFingerprint": self.external_validation_fingerprint,
            },
            "blockers": self.blockers,
            "automaticApproval": False,
            "automaticTrading": False,
        }


class MarketWeightingReadinessService:
    """Fail-closed readiness for canonical market weighting.

    This service reports whether the engineering evidence required to create a
    weighting proposal is complete. It never approves weights and never turns
    fixtures or diagnostics into production evidence.
    """

    DEFAULT_MINIMUM_IDENTITY_MARKET_CAP_COVERAGE = 0.95
    DEFAULT_MINIMUM_DOMICILE_MARKET_CAP_COVERAGE = 0.90
    DEFAULT_MINIMUM_CANONICAL_ISSUER_COUNT = 1000

    def __init__(self, *, database: AthenaDatabase | None = None, minimum_identity_market_cap_coverage: float = DEFAULT_MINIMUM_IDENTITY_MARKET_CAP_COVERAGE, minimum_domicile_market_cap_coverage: float = DEFAULT_MINIMUM_DOMICILE_MARKET_CAP_COVERAGE, minimum_canonical_issuer_count: int = DEFAULT_MINIMUM_CANONICAL_ISSUER_COUNT, external_validation_repository: MarketWeightingExternalValidationRepository | None = None) -> None:
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
        self._external_validation_repository = external_validation_repository if external_validation_repository is not None else MarketWeightingExternalValidationRepository(database=self._database)

    def get_report(self, *, as_of: datetime | None = None) -> MarketWeightingReadinessReport:
        identity = IssuerIdentityCoverageService(database=self._database).get_report()
        canonical = CanonicalMarketCapService(database=self._database).get_report()
        canonical_listings = CanonicalListingSelectionService(database=self._database).get_report()
        evidence_fingerprint = self._identity_evidence_fingerprint(
            identity_market_cap_coverage=identity.market_cap_coverage,
            domicile_market_cap_coverage=canonical.domicile_market_cap_coverage,
            canonical_issuer_count=canonical.canonical_issuer_count,
            region_market_cap_usd=dict(canonical.region_market_cap_usd),
            ambiguous_listing_count=canonical_listings.ambiguous_issuer_count,
            no_domestic_listing_count=canonical_listings.no_domestic_listing_count,
            canonical_listing_market_cap_count=canonical.canonical_listing_market_cap_count,
            median_fallback_market_cap_count=canonical.median_fallback_market_cap_count,
        )
        validation = self._external_validation_repository.get_latest_for_evidence(identity_evidence_fingerprint=evidence_fingerprint, as_of=as_of)
        return MarketWeightingReadinessReport(
            identity_market_cap_coverage=identity.market_cap_coverage,
            domicile_market_cap_coverage=canonical.domicile_market_cap_coverage,
            canonical_issuer_count=canonical.canonical_issuer_count,
            region_market_cap_usd=dict(canonical.region_market_cap_usd),
            minimum_identity_market_cap_coverage=self._minimum_identity_market_cap_coverage,
            minimum_domicile_market_cap_coverage=self._minimum_domicile_market_cap_coverage,
            minimum_canonical_issuer_count=self._minimum_canonical_issuer_count,
            external_validation_passed=validation is not None,
            external_validation_reference=str(validation["reference"]) if validation is not None else None,
            canonical_listing_ambiguous_issuer_count=canonical_listings.ambiguous_issuer_count,
            canonical_listing_no_domestic_issuer_count=canonical_listings.no_domestic_listing_count,
            canonical_listing_market_cap_count=canonical.canonical_listing_market_cap_count,
            median_fallback_market_cap_count=canonical.median_fallback_market_cap_count,
            identity_evidence_fingerprint=evidence_fingerprint,
            external_validation_fingerprint=str(validation["validationFingerprint"]) if validation is not None else None,
        )

    def _identity_evidence_fingerprint(self, *, identity_market_cap_coverage: float, domicile_market_cap_coverage: float, canonical_issuer_count: int, region_market_cap_usd: dict[str, float], ambiguous_listing_count: int, no_domestic_listing_count: int, canonical_listing_market_cap_count: int, median_fallback_market_cap_count: int) -> str:
        evidence = {
            "method": "canonical_domestic_listing_else_median_with_domicile",
            "identityMarketCapCoverage": float(identity_market_cap_coverage),
            "domicileMarketCapCoverage": float(domicile_market_cap_coverage),
            "canonicalIssuerCount": int(canonical_issuer_count),
            "regionMarketCapUsd": {key: float(value) for key, value in sorted(region_market_cap_usd.items())},
            "canonicalListingAmbiguousIssuerCount": int(ambiguous_listing_count),
            "canonicalListingNoDomesticIssuerCount": int(no_domestic_listing_count),
            "canonicalListingMarketCapCount": int(canonical_listing_market_cap_count),
            "medianFallbackMarketCapCount": int(median_fallback_market_cap_count),
        }
        encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
