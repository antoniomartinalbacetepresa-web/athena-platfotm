from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.issuer_resolution_pipeline_service import (
    IssuerResolutionPipelineService,
)


class FakeSecProvider:
    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        return [
            {
                "cik": "0000320193",
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "exchange": "Nasdaq",
            }
        ]

    def get_submissions(self, cik: str | int) -> dict[str, object]:
        assert str(cik) == "0000320193"
        return {
            "stateOfIncorporation": "CA",
            "stateOfIncorporationDescription": "CALIFORNIA",
        }


def test_pipeline_applies_identity_domicile_and_diagnostics(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 500.0,
        }
    )

    report = IssuerResolutionPipelineService(
        database=database,
        sec_provider=FakeSecProvider(),
    ).run(domicile_limit=10)
    api = report.to_api_dict()

    assert api["identity"]["linkedListingCount"] == 1
    assert api["domicile"]["resolvedIssuerCount"] == 1
    assert api["coverage"]["listingCoverage"] == 1.0
    assert api["coverage"]["domicileCoverage"] == 1.0
    assert api["canonicalMarketCap"]["canonicalIssuerCount"] == 1
    assert api["canonicalMarketCap"]["domicileMarketCapCoverage"] == 1.0
    assert api["canonicalListingSelection"]["selectedIssuerCount"] == 1
    assert api["isWeightingReady"] is False
