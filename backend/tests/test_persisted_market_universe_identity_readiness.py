from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.persisted_market_universe_service import PersistedMarketUniverseService


class EmptyFallback:
    def get_universe(self) -> list[dict[str, object]]:
        return []


def test_universe_status_exposes_canonical_identity_readiness(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    us_id = instruments.upsert(
        {
            "symbol": "US",
            "companyName": "US Company",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 600.0,
        }
    )
    instruments.upsert_many(
        [
            {
                "symbol": "EU",
                "companyName": "EU Company",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "GER",
                "marketCap": 300.0,
            },
            {
                "symbol": "ASIA",
                "companyName": "Asia Company",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "marketCap": 100.0,
            },
        ]
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="US-1",
        canonical_name="US Company",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    identities.link_instrument(
        instrument_id=us_id,
        issuer_id=issuer_id,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = PersistedMarketUniverseService(
        database=database,
        fallback_service=EmptyFallback(),
        minimum_global_usable_count=3,
        minimum_usable_per_region=1,
    ).get_quality_report()
    api = report.to_api_dict()

    assert report.is_global_ready is True
    assert report.is_weighting_ready is False
    assert report.canonical_identity_listing_coverage == pytest.approx(1 / 3)
    assert report.canonical_identity_market_cap_coverage == pytest.approx(0.6)
    assert report.canonical_domicile_market_cap_coverage == pytest.approx(1.0)
    assert report.canonical_issuer_count == 1
    assert api["issuerIdentityReadiness"]["listingCoverage"] == pytest.approx(1 / 3)
    assert api["issuerIdentityReadiness"]["marketCapCoverage"] == pytest.approx(0.6)
    assert api["issuerIdentityReadiness"]["domicileMarketCapCoverage"] == pytest.approx(
        1.0
    )
    assert api["issuerIdentityReadiness"]["ready"] is False
    assert api["weightingStatus"] == (
        "issuer_identity_and_domicile_calibration_required"
    )
