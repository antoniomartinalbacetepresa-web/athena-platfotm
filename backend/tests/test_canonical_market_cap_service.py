from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_market_cap_service import CanonicalMarketCapService


def _insert(
    repository: InstrumentRepository,
    *,
    symbol: str,
    market_cap: float,
    country: str,
    region: str,
) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": country,
            "regionKey": region,
            "exchangeShortName": symbol,
            "marketCap": market_cap,
        }
    )


def test_canonical_market_cap_counts_same_issuer_once_with_median(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    us_id = _insert(
        instruments,
        symbol="AAA",
        market_cap=500.0,
        country="United States",
        region="america",
    )
    de_id = _insert(
        instruments,
        symbol="AAA.DE",
        market_cap=490.0,
        country="Germany",
        region="europe",
    )
    mx_id = _insert(
        instruments,
        symbol="AAA.MX",
        market_cap=2000.0,
        country="Mexico",
        region="america",
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ISSUER-A",
        canonical_name="Issuer A",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (us_id, de_id, mx_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.linked_listing_count == 3
    assert report.canonical_issuer_count == 1
    assert report.raw_linked_market_cap_usd == pytest.approx(2990.0)
    assert report.canonical_market_cap_usd == pytest.approx(500.0)
    assert report.duplicate_excess_market_cap_usd == pytest.approx(2490.0)
    assert report.domicile_resolved_market_cap_usd == pytest.approx(500.0)
    assert report.region_market_cap_usd == pytest.approx(
        {"america": 500.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.region_weights == pytest.approx(
        {"america": 1.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.multi_listing_issuer_count == 1
    assert report.cross_listing_ratio_observation_count == 1
    assert report.median_cross_listing_market_cap_ratio == pytest.approx(2000.0 / 490.0)
    assert report.max_cross_listing_market_cap_ratio == pytest.approx(2000.0 / 490.0)
    consistency = report.to_api_dict()["crossListingMarketCapConsistency"]
    assert consistency["multiListingIssuerCount"] == 1
    assert consistency["ratioObservationCount"] == 1


def test_canonical_market_cap_keeps_unresolved_domicile_out_of_region_weights(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    us_id = _insert(
        instruments,
        symbol="US",
        market_cap=300.0,
        country="United States",
        region="america",
    )
    unknown_id = _insert(
        instruments,
        symbol="UNKNOWN",
        market_cap=700.0,
        country="Germany",
        region="europe",
    )

    identities = IssuerIdentityRepository(database=database)
    resolved_issuer = identities.upsert_external_issuer(
        source_provider="official",
        external_id="RESOLVED",
        canonical_name="Resolved",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    unresolved_issuer = identities.upsert_external_issuer(
        source_provider="official",
        external_id="UNRESOLVED",
        canonical_name="Unresolved",
        evidence_confidence=1.0,
    )
    identities.link_instrument(
        instrument_id=us_id,
        issuer_id=resolved_issuer,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )
    identities.link_instrument(
        instrument_id=unknown_id,
        issuer_id=unresolved_issuer,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.canonical_market_cap_usd == pytest.approx(1000.0)
    assert report.domicile_resolved_market_cap_usd == pytest.approx(300.0)
    assert report.domicile_unresolved_market_cap_usd == pytest.approx(700.0)
    assert report.domicile_market_cap_coverage == pytest.approx(0.3)
    assert report.region_market_cap_usd == pytest.approx(
        {"america": 300.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.multi_listing_issuer_count == 0
    assert report.cross_listing_ratio_observation_count == 0
    assert report.median_cross_listing_market_cap_ratio is None
    assert report.max_cross_listing_market_cap_ratio is None
    assert report.to_api_dict()["readyForRegionalWeighting"] is False
