from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.market_weighting_readiness_service import (
    MarketWeightingReadinessReport,
    MarketWeightingReadinessService,
)


def _report(
    *,
    identity_coverage: float = 0.97,
    domicile_coverage: float = 0.93,
    issuer_count: int = 5000,
    regions: dict[str, float] | None = None,
    external_validation_passed: bool = True,
    ambiguous_listing_count: int = 0,
    no_domestic_listing_count: int = 0,
    canonical_listing_cap_count: int = 4500,
    median_fallback_cap_count: int = 500,
) -> MarketWeightingReadinessReport:
    return MarketWeightingReadinessReport(
        identity_market_cap_coverage=identity_coverage,
        domicile_market_cap_coverage=domicile_coverage,
        canonical_issuer_count=issuer_count,
        region_market_cap_usd=(
            regions
            if regions is not None
            else {"america": 60.0, "europe": 20.0, "asia": 20.0}
        ),
        minimum_identity_market_cap_coverage=0.95,
        minimum_domicile_market_cap_coverage=0.90,
        minimum_canonical_issuer_count=1000,
        external_validation_passed=external_validation_passed,
        external_validation_reference=(
            "independent_reference" if external_validation_passed else None
        ),
        canonical_listing_ambiguous_issuer_count=ambiguous_listing_count,
        canonical_listing_no_domestic_issuer_count=no_domestic_listing_count,
        canonical_listing_market_cap_count=canonical_listing_cap_count,
        median_fallback_market_cap_count=median_fallback_cap_count,
    )


def test_weighting_readiness_requires_all_evidence() -> None:
    report = _report()

    assert report.ready is True
    assert report.blockers == ()
    assert report.all_regions_represented is True
    assert report.external_validation_evidence_complete is True
    api = report.to_api_dict()
    assert api["method"] == "canonical_domestic_listing_else_median_with_domicile"
    assert api["canonicalMarketCapDiagnostics"] == {
        "canonicalListingCount": 4500,
        "medianFallbackCount": 500,
        "fallbackIsDiagnosticOnly": True,
    }
    assert api["canonicalListingValidation"]["domesticListingCoverageComplete"] is True


def test_weighting_readiness_keeps_external_validation_as_hard_gate() -> None:
    report = _report(external_validation_passed=False)

    assert report.ready is False
    assert report.blockers == ("external_market_cap_validation_required",)
    api = report.to_api_dict()
    assert api["externalValidation"]["passed"] is False
    assert api["externalValidation"]["evidenceComplete"] is False
    assert api["ready"] is False


def test_weighting_readiness_requires_external_validation_reference() -> None:
    report = replace(_report(), external_validation_reference=None)

    assert report.external_validation_passed is True
    assert report.external_validation_evidence_complete is False
    assert report.ready is False
    assert report.blockers == ("external_market_cap_validation_required",)
    assert report.to_api_dict()["externalValidation"] == {
        "passed": True,
        "reference": None,
        "evidenceComplete": False,
    }


def test_weighting_readiness_blocks_ambiguous_canonical_listings() -> None:
    report = _report(ambiguous_listing_count=2)

    assert report.ready is False
    assert report.blockers == ("ambiguous_canonical_listings_require_resolution",)
    validation = report.to_api_dict()["canonicalListingValidation"]
    assert validation["ambiguousIssuerCount"] == 2
    assert validation["ambiguityResolved"] is False


def test_weighting_readiness_blocks_missing_domestic_canonical_listing() -> None:
    report = _report(no_domestic_listing_count=3)

    assert report.ready is False
    assert report.blockers == ("canonical_domestic_listings_required",)
    validation = report.to_api_dict()["canonicalListingValidation"]
    assert validation["noDomesticListingIssuerCount"] == 3
    assert validation["domesticListingCoverageComplete"] is False


def test_weighting_readiness_reports_each_structural_blocker() -> None:
    report = _report(
        identity_coverage=0.80,
        domicile_coverage=0.70,
        issuer_count=500,
        regions={"america": 60.0, "europe": 40.0, "asia": 0.0},
        external_validation_passed=False,
    )

    assert report.ready is False
    assert report.blockers == (
        "insufficient_canonical_identity_market_cap_coverage",
        "insufficient_issuer_domicile_market_cap_coverage",
        "insufficient_canonical_issuer_count",
        "required_regions_not_represented",
        "external_market_cap_validation_required",
    )


def test_weighting_readiness_configuration_is_conservative_and_validated() -> None:
    assert MarketWeightingReadinessService.DEFAULT_MINIMUM_IDENTITY_MARKET_CAP_COVERAGE == 0.95
    assert MarketWeightingReadinessService.DEFAULT_MINIMUM_DOMICILE_MARKET_CAP_COVERAGE == 0.90
    assert MarketWeightingReadinessService.DEFAULT_MINIMUM_CANONICAL_ISSUER_COUNT == 1000

    with pytest.raises(ValueError, match="minimum_identity_market_cap_coverage"):
        MarketWeightingReadinessService(minimum_identity_market_cap_coverage=0)

    with pytest.raises(ValueError, match="minimum_domicile_market_cap_coverage"):
        MarketWeightingReadinessService(minimum_domicile_market_cap_coverage=1.1)

    with pytest.raises(ValueError, match="minimum_canonical_issuer_count"):
        MarketWeightingReadinessService(minimum_canonical_issuer_count=0)
