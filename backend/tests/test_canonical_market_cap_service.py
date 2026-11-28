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
    is_primary: bool = False,
    exchange: str | None = None,
    currency: str = "USD",
    instrument_type: str = "EQUITY",
) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": country,
            "regionKey": region,
            "exchangeShortName": exchange if exchange is not None else symbol,
            "currency": currency,
            "instrumentType": instrument_type,
            "marketCap": market_cap,
            "isPrimaryListing": is_primary,
        }
    )


def test_canonical_market_cap_counts_same_issuer_once_using_domestic_listing(
    tmp_path: Path,
) -> None:
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
    assert report.canonical_listing_market_cap_count == 1
    assert report.median_fallback_market_cap_count == 0
    assert report.multi_listing_issuer_count == 1
    assert report.cross_listing_ratio_observation_count == 1
    assert report.median_cross_listing_market_cap_ratio == pytest.approx(2000.0 / 490.0)
    assert report.max_cross_listing_market_cap_ratio == pytest.approx(2000.0 / 490.0)
    consistency = report.to_api_dict()["crossListingMarketCapConsistency"]
    assert consistency["multiListingIssuerCount"] == 1
    assert consistency["ratioObservationCount"] == 1


def test_canonical_market_cap_prefers_explicit_primary_domestic_listing(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    primary_id = _insert(
        instruments,
        symbol="PRIMARY",
        market_cap=300.0,
        country="USA",
        region="america",
        is_primary=True,
    )
    secondary_domestic_id = _insert(
        instruments,
        symbol="SECONDARY",
        market_cap=450.0,
        country="United States",
        region="america",
    )
    foreign_id = _insert(
        instruments,
        symbol="FOREIGN.DE",
        market_cap=500.0,
        country="Germany",
        region="europe",
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ISSUER-PRIMARY",
        canonical_name="Primary Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (primary_id, secondary_domestic_id, foreign_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.canonical_market_cap_usd == pytest.approx(300.0)
    assert report.canonical_listing_market_cap_count == 1
    assert report.median_fallback_market_cap_count == 0
    selection = report.to_api_dict()["marketCapSelection"]
    assert selection["canonicalListingCount"] == 1
    assert selection["medianFallbackCount"] == 0


def test_canonical_market_cap_uses_median_only_when_domestic_selection_is_ambiguous(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    first_id = _insert(
        instruments,
        symbol="CLASS-A",
        market_cap=300.0,
        country="United States",
        region="america",
    )
    second_id = _insert(
        instruments,
        symbol="CLASS-B",
        market_cap=500.0,
        country="United States",
        region="america",
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ISSUER-AMBIGUOUS",
        canonical_name="Ambiguous Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (first_id, second_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.canonical_market_cap_usd == pytest.approx(400.0)
    assert report.canonical_listing_market_cap_count == 0
    assert report.median_fallback_market_cap_count == 1
    assert report.to_api_dict()["readyForRegionalWeighting"] is False


def test_canonical_market_cap_uses_only_identity_complete_canonical_listing(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    incomplete_primary_id = _insert(
        instruments,
        symbol="PRIMARY-NO-FX",
        market_cap=100.0,
        country="United States",
        region="america",
        is_primary=True,
        currency="",
    )
    complete_secondary_id = _insert(
        instruments,
        symbol="SECONDARY-COMPLETE",
        market_cap=300.0,
        country="United States",
        region="america",
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ISSUER-IDENTITY-GATED",
        canonical_name="Identity Gated Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (incomplete_primary_id, complete_secondary_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.raw_linked_market_cap_usd == pytest.approx(400.0)
    assert report.canonical_market_cap_usd == pytest.approx(300.0)
    assert report.canonical_listing_market_cap_count == 1
    assert report.median_fallback_market_cap_count == 0
    assert report.region_market_cap_usd == pytest.approx(
        {"america": 300.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.to_api_dict()["readyForRegionalWeighting"] is False


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
    assert report.canonical_listing_market_cap_count == 1
    assert report.median_fallback_market_cap_count == 1
    assert report.multi_listing_issuer_count == 0
    assert report.cross_listing_ratio_observation_count == 0
    assert report.median_cross_listing_market_cap_ratio is None
    assert report.max_cross_listing_market_cap_ratio is None
    assert report.to_api_dict()["readyForRegionalWeighting"] is False


def test_canonical_market_cap_excludes_infinite_primary_from_all_aggregates(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    infinite_primary_id = _insert(
        instruments,
        symbol="INFINITE-PRIMARY",
        market_cap=float("inf"),
        country="United States",
        region="america",
        is_primary=True,
    )
    valid_secondary_id = _insert(
        instruments,
        symbol="VALID-SECONDARY",
        market_cap=300.0,
        country="United States",
        region="america",
    )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ISSUER-NON-FINITE",
        canonical_name="Non Finite Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (infinite_primary_id, valid_secondary_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalMarketCapService(database=database).get_report()

    assert report.linked_listing_count == 1
    assert report.raw_linked_market_cap_usd == pytest.approx(300.0)
    assert report.canonical_market_cap_usd == pytest.approx(300.0)
    assert report.duplicate_excess_market_cap_usd == pytest.approx(0.0)
    assert report.canonical_listing_market_cap_count == 0
    assert report.median_fallback_market_cap_count == 1
    assert report.multi_listing_issuer_count == 0
    assert report.cross_listing_ratio_observation_count == 0
    assert report.region_market_cap_usd == pytest.approx(
        {"america": 300.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.region_weights == pytest.approx(
        {"america": 1.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.to_api_dict()["readyForRegionalWeighting"] is False


@pytest.mark.parametrize(
    "invalid_cap",
    [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, True, None],
)
def test_canonical_market_cap_selection_ignores_invalid_caps(
    tmp_path: Path,
    invalid_cap: object,
) -> None:
    service = CanonicalMarketCapService(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    cap, used_canonical = service._select_issuer_market_cap(
        issuer_id=7,
        listings=[
            {"instrument_id": 1, "market_cap_usd": invalid_cap},
            {"instrument_id": 2, "market_cap_usd": 250.0},
        ],
        selected_instrument_by_issuer={7: 1},
    )

    assert cap == pytest.approx(250.0)
    assert used_canonical is False


def test_canonical_market_cap_weights_fail_closed_on_invalid_caps(
    tmp_path: Path,
) -> None:
    service = CanonicalMarketCapService(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    weights = service._weights_from_caps(
        {
            "america": 300.0,
            "europe": float("inf"),
            "asia": float("nan"),
        }
    )

    assert weights == pytest.approx(
        {"america": 1.0, "europe": 0.0, "asia": 0.0}
    )
