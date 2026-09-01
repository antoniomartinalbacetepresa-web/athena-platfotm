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
        elif index < 80:
            region = "europe"
            country = "Germany"
        else:
            region = "asia"
            country = "Japan"

        rows.append(
            {
                "symbol": f"S{index}",
                "companyName": f"Company {index}",
                "country": country,
                "regionKey": region,
                "exchangeShortName": "TEST",
                "marketCap": float(100 - index),
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
