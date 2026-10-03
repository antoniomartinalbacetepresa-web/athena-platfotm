from app.services.persisted_market_universe_service import (
    MarketUniverseQualityReport,
)


def test_weighting_status_describes_canonical_issuer_calibration() -> None:
    report = MarketUniverseQualityReport(
        active_count=100,
        market_cap_ready_count=90,
        country_ready_count=90,
        globally_usable_count=90,
        region_counts={"america": 30, "europe": 30, "asia": 30},
        represented_regions=("america", "europe", "asia"),
        minimum_global_usable_count=100,
        minimum_usable_per_region=20,
        minimum_usable_coverage=0.3,
        is_global_ready=False,
        using_fallback=True,
    )

    api = report.to_api_dict()

    assert api["isWeightingReady"] is False
    assert api["weightingMethod"] == (
        "canonical_issuer_market_cap_pending_validation"
    )
    assert api["weightingStatus"] == (
        "issuer_identity_and_domicile_calibration_required"
    )
    assert api["issuerIdentityReadiness"] == {
        "listingCoverage": 0.0,
        "marketCapCoverage": 0.0,
        "domicileMarketCapCoverage": 0.0,
        "canonicalIssuerCount": 0,
        "ready": False,
    }
