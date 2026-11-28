from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_market_cap_service import CanonicalMarketCapService


def test_canonical_market_cap_excludes_known_etfs_and_funds(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)

    stock_id = instruments.upsert(
        {
            "symbol": "ACME",
            "companyName": "Acme Corporation",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
            "marketCap": 500.0,
        }
    )
    etf_id = instruments.upsert(
        {
            "symbol": "ACMEETF",
            "companyName": "Acme ETF",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "ARCX",
            "instrumentType": "etf",
            "marketCap": 9000.0,
        }
    )
    fund_id = instruments.upsert(
        {
            "symbol": "ACMEFUND",
            "companyName": "Acme Fund",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "MUTF",
            "instrumentType": "fund",
            "marketCap": 7000.0,
        }
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ACME-ISSUER",
        canonical_name="Acme Corporation",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )

    for instrument_id in (stock_id, etf_id, fund_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.linked_listing_count == 1
    assert report.canonical_issuer_count == 1
    assert report.raw_linked_market_cap_usd == pytest.approx(500.0)
    assert report.canonical_market_cap_usd == pytest.approx(500.0)
    assert report.region_market_cap_usd["america"] == pytest.approx(500.0)
    assert report.to_api_dict()["excludedKnownNonEquityTypes"] == ["etf", "fund"]
