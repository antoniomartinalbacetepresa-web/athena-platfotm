from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.sec_issuer_resolution_preview_service import (
    SecIssuerResolutionPreviewService,
)


class FakeSecProvider:
    def __init__(self, associations: list[dict[str, str]]) -> None:
        self.associations = associations

    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        return self.associations


def test_sec_preview_measures_us_listing_and_market_cap_coverage(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)
    repository.upsert_many(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "marketCap": 500.0,
            },
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NMS",
                "marketCap": 400.0,
            },
            {
                "symbol": "UNKNOWN",
                "companyName": "Unknown Inc",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "marketCap": 100.0,
            },
            {
                "symbol": "SAP.DE",
                "companyName": "SAP SE",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "marketCap": 200.0,
            },
        ]
    )
    provider = FakeSecProvider(
        [
            {
                "cik": "0000320193",
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "exchange": "Nasdaq",
            },
            {
                "cik": "0000789019",
                "name": "Microsoft Corp",
                "ticker": "MSFT",
                "exchange": "Nasdaq",
            },
        ]
    )

    report = SecIssuerResolutionPreviewService(
        database=database,
        sec_provider=provider,
    ).get_report()

    assert report.eligible_us_listing_count == 3
    assert report.matched_listing_count == 2
    assert report.ambiguous_listing_count == 0
    assert report.unmatched_listing_count == 1
    assert report.matched_unique_cik_count == 2
    assert report.listing_coverage == pytest.approx(2 / 3)
    assert report.eligible_market_cap_usd == pytest.approx(1000.0)
    assert report.matched_market_cap_usd == pytest.approx(900.0)
    assert report.market_cap_coverage == pytest.approx(0.9)
    assert report.top_unmatched_listings[0]["symbol"] == "UNKNOWN"


def test_sec_preview_flags_duplicate_ticker_to_multiple_ciks_as_ambiguous(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    InstrumentRepository(database=database).upsert(
        {
            "symbol": "DUP",
            "companyName": "Duplicate Ticker Example",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 250.0,
        }
    )
    provider = FakeSecProvider(
        [
            {
                "cik": "0000000001",
                "name": "Issuer One",
                "ticker": "DUP",
                "exchange": "Nasdaq",
            },
            {
                "cik": "0000000002",
                "name": "Issuer Two",
                "ticker": "DUP",
                "exchange": "NYSE",
            },
        ]
    )

    report = SecIssuerResolutionPreviewService(
        database=database,
        sec_provider=provider,
    ).get_report()

    assert report.matched_listing_count == 0
    assert report.ambiguous_listing_count == 1
    assert report.unmatched_listing_count == 0
    assert report.matched_market_cap_usd == pytest.approx(0.0)
    assert report.top_ambiguous_listings[0]["candidateCiks"] == [
        "0000000001",
        "0000000002",
    ]


def test_sec_preview_ignores_non_us_and_missing_market_cap_rows(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)
    repository.upsert_many(
        [
            {
                "symbol": "NO_CAP",
                "companyName": "No Cap",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "7203.T",
                "companyName": "Toyota Motor Corporation",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "marketCap": 300.0,
            },
        ]
    )

    report = SecIssuerResolutionPreviewService(
        database=database,
        sec_provider=FakeSecProvider([]),
    ).get_report()

    assert report.eligible_us_listing_count == 0
    assert report.listing_coverage == pytest.approx(0.0)
    assert report.market_cap_coverage == pytest.approx(0.0)
