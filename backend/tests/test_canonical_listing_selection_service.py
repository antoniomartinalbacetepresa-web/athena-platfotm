from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_listing_selection_service import (
    CanonicalListingSelectionService,
)


def _listing(
    repository: InstrumentRepository,
    *,
    symbol: str,
    country: str,
    region: str,
    is_primary: bool = False,
) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": country,
            "regionKey": region,
            "exchangeShortName": symbol,
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 100.0,
            "isPrimaryListing": is_primary,
        }
    )


def test_selector_uses_single_domestic_listing(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    domestic_id = _listing(
        instruments,
        symbol="AAA",
        country="United States",
        region="america",
    )
    foreign_id = _listing(
        instruments,
        symbol="AAA.DE",
        country="Germany",
        region="europe",
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="AAA",
        canonical_name="Issuer AAA",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (domestic_id, foreign_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.eligible_issuer_count == 1
    assert report.selected_issuer_count == 1
    assert report.ambiguous_issuer_count == 0
    assert report.no_domestic_listing_count == 0
    assert report.selections[0]["symbol"] == "AAA"
    assert report.selections[0]["selectionMethod"] == "single_domestic_listing"


def test_selector_matches_country_aliases_without_conflating_listing_and_domicile(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    domestic_id = _listing(
        instruments,
        symbol="ALIAS",
        country="USA",
        region="america",
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="ALIAS",
        canonical_name="Alias Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    identities.link_instrument(
        instrument_id=domestic_id,
        issuer_id=issuer_id,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.selected_issuer_count == 1
    assert report.no_domestic_listing_count == 0
    assert report.selections[0]["symbol"] == "ALIAS"
    assert report.selections[0]["domicileCountry"] == "United States"


def test_selector_prefers_explicit_primary_among_multiple_domestic_listings(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    first_id = _listing(
        instruments,
        symbol="CLASSA",
        country="United States",
        region="america",
        is_primary=True,
    )
    second_id = _listing(
        instruments,
        symbol="CLASSB",
        country="United States",
        region="america",
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="MULTI",
        canonical_name="Multi Class",
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

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.selected_issuer_count == 1
    assert report.selections[0]["symbol"] == "CLASSA"
    assert report.selections[0]["selectionMethod"] == (
        "explicit_primary_domestic_listing"
    )


def test_selector_marks_multiple_domestic_classes_ambiguous(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    first_id = _listing(
        instruments,
        symbol="GOOG",
        country="United States",
        region="america",
    )
    second_id = _listing(
        instruments,
        symbol="GOOGL",
        country="United States",
        region="america",
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id="0001652044",
        canonical_name="Alphabet Inc.",
        evidence_confidence=0.95,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in (first_id, second_id):
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="sec_company_tickers_exchange",
            resolution_method="exact_ticker_unique_cik",
            confidence=0.95,
        )

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.selected_issuer_count == 0
    assert report.ambiguous_issuer_count == 1
    assert set(report.ambiguous[0]["candidateSymbols"]) == {"GOOG", "GOOGL"}
    assert report.selection_coverage == pytest.approx(0.0)


def test_selector_does_not_choose_foreign_listing_without_domestic_candidate(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    foreign_id = _listing(
        instruments,
        symbol="USCO.DE",
        country="Germany",
        region="europe",
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="USCO",
        canonical_name="US Company",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    identities.link_instrument(
        instrument_id=foreign_id,
        issuer_id=issuer_id,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.selected_issuer_count == 0
    assert report.no_domestic_listing_count == 1


def test_selector_reports_listing_identity_gap_dimensions(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    rows = [
        {
            "symbol": "COMPLETE",
            "exchangeShortName": "NMS",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "isPrimaryListing": True,
        },
        {
            "symbol": "NOEX",
            "exchangeShortName": "",
            "currency": "USD",
            "instrumentType": "EQUITY",
        },
        {
            "symbol": "BADFX",
            "exchangeShortName": "NMS",
            "currency": "US",
            "instrumentType": "EQUITY",
        },
        {
            "symbol": "NOTYPE",
            "exchangeShortName": "NMS",
            "currency": "USD",
            "instrumentType": "UNKNOWN",
        },
    ]
    instrument_ids = []
    for row in rows:
        instrument_ids.append(
            instruments.upsert(
                {
                    "symbol": row["symbol"],
                    "companyName": row["symbol"],
                    "country": "United States",
                    "regionKey": "america",
                    "exchangeShortName": row["exchangeShortName"],
                    "currency": row["currency"],
                    "instrumentType": row["instrumentType"],
                    "marketCap": 100.0,
                    "isPrimaryListing": row.get("isPrimaryListing", False),
                }
            )
        )

    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="IDENTITY-GAPS",
        canonical_name="Identity Gaps Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for instrument_id in instrument_ids:
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    report = CanonicalListingSelectionService(database=database).get_report()
    api = report.to_api_dict()

    assert report.selected_issuer_count == 1
    assert report.domestic_listing_count == 4
    assert report.complete_identity_listing_count == 1
    assert report.missing_exchange_listing_count == 1
    assert report.invalid_currency_listing_count == 1
    assert report.unknown_instrument_type_listing_count == 1
    assert report.complete_identity_coverage == pytest.approx(0.25)
    assert api["completeIdentityCoverage"] == pytest.approx(0.25)
