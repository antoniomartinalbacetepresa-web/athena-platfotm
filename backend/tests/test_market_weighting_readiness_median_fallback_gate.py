from app.services.market_weighting_readiness_service import MarketWeightingReadinessReport


def _report(*, median_fallback_count: int) -> MarketWeightingReadinessReport:
    return MarketWeightingReadinessReport(
        identity_market_cap_coverage=1.0,
        domicile_market_cap_coverage=1.0,
        canonical_issuer_count=1000,
        region_market_cap_usd={"america": 60.0, "europe": 30.0, "asia": 10.0},
        minimum_identity_market_cap_coverage=0.95,
        minimum_domicile_market_cap_coverage=0.90,
        minimum_canonical_issuer_count=1000,
        external_validation_passed=True,
        external_validation_reference="human-review-2026-09-15",
        canonical_listing_ambiguous_issuer_count=0,
        canonical_listing_no_domestic_issuer_count=0,
        canonical_listing_market_cap_count=1000,
        median_fallback_market_cap_count=median_fallback_count,
        identity_evidence_fingerprint="a" * 64,
        external_validation_fingerprint="b" * 64,
    )


def test_median_fallback_market_cap_blocks_weighting_even_when_other_gates_pass() -> None:
    report = _report(median_fallback_count=1)

    assert report.ready is False
    assert "median_fallback_market_caps_require_resolution" in report.blockers
    payload = report.to_api_dict()
    assert payload["canonicalMarketCapDiagnostics"]["fallbackIsDiagnosticOnly"] is True
    assert payload["canonicalMarketCapDiagnostics"]["fallbackResolvedForActivation"] is False


def test_zero_median_fallback_removes_only_the_fallback_blocker() -> None:
    report = _report(median_fallback_count=0)

    assert "median_fallback_market_caps_require_resolution" not in report.blockers
    assert report.to_api_dict()["canonicalMarketCapDiagnostics"]["fallbackResolvedForActivation"] is True
    # Readiness remains governed by every other canonical/external evidence gate;
    # this regression intentionally does not assert global readiness from a
    # hand-built report, because fixtures are not production evidence.
