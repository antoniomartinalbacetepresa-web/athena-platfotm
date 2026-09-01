from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.issuer_resolution_diagnostics_service import (
    IssuerResolutionDiagnosticsService,
)


def test_issuer_resolution_uses_explicit_identity_and_primary_listing(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "AAA",
                "companyName": "Alpha Corp",
                "issuerId": "ISSUER-ALPHA",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "isPrimaryListing": True,
                "marketCap": 500.0,
            },
            {
                "symbol": "AAA.DE",
                "companyName": "Alpha Corp",
                "issuerId": "ISSUER-ALPHA",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "isPrimaryListing": False,
                "marketCap": 495.0,
            },
            {
                "symbol": "BBB.T",
                "companyName": "Beta Co",
                "issuerId": "ISSUER-BETA",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "isPrimaryListing": True,
                "marketCap": 300.0,
            },
            {
                "symbol": "UNRESOLVED",
                "companyName": "Unresolved Co",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "marketCap": 100.0,
            },
        ]
    )

    report = IssuerResolutionDiagnosticsService(database=database).get_report()

    assert report.usable_listing_count == 4
    assert report.listings_with_issuer_id_count == 3
    assert report.issuer_id_listing_coverage == pytest.approx(0.75)
    assert report.unresolved_listing_count == 1
    assert report.explicit_issuer_count == 2
    assert report.primary_listing_count == 2
    assert report.issuer_groups_without_primary_listing_count == 0
    assert report.issuer_groups_with_multiple_primary_listings_count == 0
    assert report.cross_region_issuer_group_count == 1
    assert report.canonical_market_cap_usd == pytest.approx(800.0)
    assert report.canonical_region_market_cap_usd == pytest.approx(
        {"america": 500.0, "europe": 0.0, "asia": 300.0}
    )
    assert report.canonical_region_weights == pytest.approx(
        {"america": 0.625, "europe": 0.0, "asia": 0.375}
    )
    assert report.has_sufficient_identity_for_weighting is False


def test_issuer_resolution_flags_missing_and_multiple_primary_listings(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "NO_PRIMARY_US",
                "companyName": "No Primary Inc",
                "issuerId": "ISSUER-NO-PRIMARY",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "marketCap": 400.0,
            },
            {
                "symbol": "NO_PRIMARY_DE",
                "companyName": "No Primary Inc",
                "issuerId": "ISSUER-NO-PRIMARY",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "marketCap": 390.0,
            },
            {
                "symbol": "MULTI_A",
                "companyName": "Multi Primary Ltd",
                "issuerId": "ISSUER-MULTI",
                "country": "United Kingdom",
                "regionKey": "europe",
                "exchangeShortName": "LSE",
                "isPrimaryListing": True,
                "marketCap": 250.0,
            },
            {
                "symbol": "MULTI_B",
                "companyName": "Multi Primary Ltd",
                "issuerId": "ISSUER-MULTI",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "isPrimaryListing": True,
                "marketCap": 245.0,
            },
        ]
    )

    report = IssuerResolutionDiagnosticsService(database=database).get_report()

    assert report.issuer_id_listing_coverage == pytest.approx(1.0)
    assert report.issuer_groups_without_primary_listing_count == 1
    assert report.issuer_groups_with_multiple_primary_listings_count == 1
    assert report.cross_region_issuer_group_count == 2
    assert report.has_sufficient_identity_for_weighting is False
    assert len(report.top_ambiguous_issuer_groups) == 2

    statuses = {
        group["selectionStatus"]
        for group in report.top_ambiguous_issuer_groups
    }
    assert statuses == {
        "fallback_largest_market_cap",
        "multiple_primary_fallback_largest",
    }


def test_issuer_resolution_can_reach_identity_gate_with_clean_explicit_data(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    rows = []
    for index in range(20):
        region, country = (
            ("america", "United States")
            if index < 8
            else ("europe", "Germany")
            if index < 14
            else ("asia", "Japan")
        )
        rows.append(
            {
                "symbol": f"S{index}",
                "companyName": f"Company {index}",
                "issuerId": f"ISSUER-{index}",
                "country": country,
                "regionKey": region,
                "exchangeShortName": "TEST",
                "isPrimaryListing": True,
                "marketCap": float(1000 - index),
            }
        )

    repository.upsert_many(rows)
    report = IssuerResolutionDiagnosticsService(database=database).get_report()

    assert report.issuer_id_listing_coverage == pytest.approx(1.0)
    assert report.issuer_groups_without_primary_listing_count == 0
    assert report.issuer_groups_with_multiple_primary_listings_count == 0
    assert report.has_sufficient_identity_for_weighting is True
    assert sum(report.canonical_region_weights.values()) == pytest.approx(1.0)
