from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.issuer_identity_coverage_service import IssuerIdentityCoverageService


def test_identity_coverage_distinguishes_identity_from_domicile(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    first_id = instruments.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 500.0,
        }
    )
    instruments.upsert(
        {
            "symbol": "UNRESOLVED",
            "companyName": "Unresolved Company",
            "country": "Germany",
            "regionKey": "europe",
            "exchangeShortName": "GER",
            "marketCap": 300.0,
        }
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.95,
    )
    identities.link_instrument(
        instrument_id=first_id,
        issuer_id=issuer_id,
        evidence_source="sec_company_tickers_exchange",
        resolution_method="exact_ticker_unique_cik",
        confidence=0.95,
    )

    report = IssuerIdentityCoverageService(database=database).get_report()

    assert report.eligible_listing_count == 2
    assert report.linked_listing_count == 1
    assert report.listing_coverage == pytest.approx(0.5)
    assert report.eligible_market_cap_usd == pytest.approx(800.0)
    assert report.linked_market_cap_usd == pytest.approx(500.0)
    assert report.market_cap_coverage == pytest.approx(0.625)
    assert report.unique_linked_issuer_count == 1
    assert report.high_confidence_linked_listing_count == 1
    assert report.domicile_resolved_issuer_count == 0
    assert report.domicile_unresolved_issuer_count == 1
    assert report.domicile_coverage == pytest.approx(0.0)
    assert report.to_api_dict()["readyForRegionalWeighting"] is False


def test_identity_coverage_counts_resolved_domicile_separately(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    instrument_id = instruments.upsert(
        {
            "symbol": "TEST",
            "companyName": "Test Company",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NYSE",
            "marketCap": 100.0,
        }
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official_registry",
        external_id="TEST-1",
        canonical_name="Test Company",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    identities.link_instrument(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        evidence_source="official_registry",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = IssuerIdentityCoverageService(database=database).get_report()

    assert report.domicile_resolved_issuer_count == 1
    assert report.domicile_unresolved_issuer_count == 0
    assert report.domicile_coverage == pytest.approx(1.0)
    assert report.to_api_dict()["readyForRegionalWeighting"] is False
