from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.market_cap_coverage_service import MarketCapCoverageService


def test_market_cap_report_sorts_by_size_and_calculates_region_weights(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    rows = []
    for index in range(100):
        if index < 50:
            region = "america"
            country = "United States"
            currency = "USD"
        elif index < 80:
            region = "europe"
            country = "Germany"
            currency = "EUR"
        else:
            region = "asia"
            country = "Japan"
            currency = "JPY"

        rows.append(
            {
                "symbol": f"S{index}",
                "companyName": f"Company {index}",
                "country": country,
                "regionKey": region,
                "exchangeShortName": "TEST",
                "currency": currency,
                "marketCap": float(100 - index),
                "marketCapLocal": float(100 - index),
                "marketCapCurrency": currency,
                "sourceProvider": "test",
                "isActive": True,
            }
        )

    repository.upsert_many(rows)

    report = MarketCapCoverageService(database=database).get_report()

    assert report.usable_count == 100
    assert report.total_market_cap_usd == pytest.approx(5050.0)
    assert report.top_market_cap_shares["top10"] == pytest.approx(955 / 5050)
    assert report.top_market_cap_shares["top50"] == pytest.approx(3775 / 5050)
    assert report.top_market_cap_shares["top100"] == pytest.approx(1.0)
    assert sum(report.region_weights.values()) == pytest.approx(1.0)
    assert report.region_weights["america"] > report.region_weights["europe"]
    assert report.region_weights["europe"] > report.region_weights["asia"]

    assert list(report.country_market_cap_usd) == [
        "United States",
        "Germany",
        "Japan",
    ]
    assert list(report.currency_market_cap_usd) == ["USD", "EUR", "JPY"]
    assert len(report.top_assets) == 50
    assert report.top_assets[0]["symbol"] == "S0"
    assert report.top_assets[0]["marketCapUsd"] == pytest.approx(100.0)
    assert report.top_assets[0]["currency"] == "USD"
    assert report.top_assets[-1]["symbol"] == "S49"

    assert report.heuristic_unique_company_count == 100
    assert report.heuristic_duplicate_group_count == 0
    assert report.heuristic_cross_region_duplicate_group_count == 0
    assert report.heuristic_deduplicated_total_market_cap_usd == pytest.approx(5050.0)
    assert report.heuristic_duplicate_excess_market_cap_usd == pytest.approx(0.0)
    assert report.heuristic_resolved_region_market_cap_usd == pytest.approx(
        report.region_market_cap_usd
    )
    assert report.heuristic_resolved_region_weights == pytest.approx(
        report.region_weights
    )
    assert report.heuristic_region_resolved_market_cap_usd == pytest.approx(5050.0)
    assert report.heuristic_region_unresolved_market_cap_usd == pytest.approx(0.0)
    assert report.heuristic_region_attribution_coverage == pytest.approx(1.0)

    api = report.to_api_dict()
    assert api["topAssets"][0]["symbol"] == "S0"
    issuer_diag = api["heuristicIssuerDeduplication"]
    assert issuer_diag["status"] == "diagnostic_only"
    assert issuer_diag["regionAttribution"]["coverage"] == pytest.approx(1.0)


def test_market_cap_report_ignores_rows_not_ready_for_global_weighting(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "OK",
                "companyName": "Usable",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "currency": "USD",
                "marketCap": 100.0,
            },
            {
                "symbol": "NO_CAP",
                "companyName": "No cap",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "XETRA",
            },
            {
                "symbol": "NO_COUNTRY",
                "companyName": "No country",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "marketCap": 80.0,
            },
        ]
    )

    report = MarketCapCoverageService(database=database).get_report()

    assert report.usable_count == 1
    assert report.total_market_cap_usd == pytest.approx(100.0)
    assert report.region_weights == {
        "america": pytest.approx(1.0),
        "europe": pytest.approx(0.0),
        "asia": pytest.approx(0.0),
    }
    assert report.country_market_cap_usd == {"United States": 100.0}
    assert report.currency_market_cap_usd == {"USD": 100.0}
    assert len(report.top_assets) == 1
    assert report.top_assets[0]["symbol"] == "OK"


def test_market_cap_report_quantifies_probable_duplicate_issuers_without_inventing_region(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "NVDA",
                "companyName": "NVIDIA Corporation",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "currency": "USD",
                "marketCap": 500.0,
            },
            {
                "symbol": "NVD.DE",
                "companyName": " NVIDIA   Corporation ",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "currency": "EUR",
                "marketCap": 495.0,
            },
            {
                "symbol": "NVDA.MX",
                "companyName": "nvidia corporation",
                "country": "Mexico",
                "regionKey": "america",
                "exchangeShortName": "MEX",
                "currency": "MXN",
                "marketCap": 490.0,
            },
            {
                "symbol": "OTHER",
                "companyName": "Other Company",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "currency": "JPY",
                "marketCap": 100.0,
            },
        ]
    )

    report = MarketCapCoverageService(database=database).get_report()

    assert report.usable_count == 4
    assert report.total_market_cap_usd == pytest.approx(1585.0)
    assert report.heuristic_unique_company_count == 2
    assert report.heuristic_duplicate_group_count == 1
    assert report.heuristic_cross_region_duplicate_group_count == 1
    assert report.heuristic_deduplicated_total_market_cap_usd == pytest.approx(595.0)
    assert report.heuristic_duplicate_excess_market_cap_usd == pytest.approx(990.0)
    assert report.heuristic_resolved_region_market_cap_usd == pytest.approx(
        {"america": 0.0, "europe": 0.0, "asia": 100.0}
    )
    assert report.heuristic_region_resolved_market_cap_usd == pytest.approx(100.0)
    assert report.heuristic_region_unresolved_market_cap_usd == pytest.approx(495.0)
    assert report.heuristic_region_attribution_coverage == pytest.approx(100 / 595)
    assert report.heuristic_resolved_region_weights == pytest.approx(
        {"america": 0.0, "europe": 0.0, "asia": 1.0}
    )

    group = report.heuristic_top_duplicate_groups[0]
    assert group["companyName"].strip().lower() == "nvidia corporation"
    assert group["listingCount"] == 3
    assert group["representativeMarketCapUsd"] == pytest.approx(495.0)
    assert group["representativeMethod"] == "median_cross_listing_market_cap"
    assert group["diagnosticReferenceSymbol"] == "NVD.DE"
    assert group["regionAttributionStatus"] == "unresolved_cross_region"
    assert group["resolvedRegionKey"] is None
    assert group["duplicateExcessMarketCapUsd"] == pytest.approx(990.0)
    assert set(group["countries"]) == {"United States", "Germany", "Mexico"}
    assert group["regions"] == ["america", "europe"]


def test_market_cap_report_uses_median_to_resist_cross_listing_outlier(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "A",
                "companyName": "Example Corp",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "currency": "USD",
                "marketCap": 100.0,
            },
            {
                "symbol": "A.DE",
                "companyName": "Example Corp",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "currency": "EUR",
                "marketCap": 102.0,
            },
            {
                "symbol": "A.BAD",
                "companyName": "Example Corp",
                "country": "United Kingdom",
                "regionKey": "europe",
                "exchangeShortName": "TEST",
                "currency": "USD",
                "marketCap": 1000.0,
            },
        ]
    )

    report = MarketCapCoverageService(database=database).get_report()

    assert report.total_market_cap_usd == pytest.approx(1202.0)
    assert report.heuristic_deduplicated_total_market_cap_usd == pytest.approx(102.0)
    assert report.heuristic_duplicate_excess_market_cap_usd == pytest.approx(1100.0)
    group = report.heuristic_top_duplicate_groups[0]
    assert group["representativeMarketCapUsd"] == pytest.approx(102.0)
    assert group["diagnosticReferenceSymbol"] == "A.DE"
