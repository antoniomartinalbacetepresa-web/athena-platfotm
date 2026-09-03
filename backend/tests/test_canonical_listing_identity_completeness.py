from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_listing_selection_service import CanonicalListingSelectionService


def test_selector_fails_closed_when_domestic_listing_has_no_exchange_identity(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    instrument_id = instruments.upsert(
        {
            "symbol": "NOEX",
            "companyName": "No Exchange Issuer",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": None,
            "marketCap": 100.0,
            "isPrimaryListing": True,
        }
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="NOEX",
        canonical_name="No Exchange Issuer",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    identities.link_instrument(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        evidence_source="official",
        resolution_method="official_identifier",
        confidence=1.0,
    )

    report = CanonicalListingSelectionService(database=database).get_report()

    assert report.eligible_issuer_count == 1
    assert report.selected_issuer_count == 0
    assert report.incomplete_listing_identity_count == 1
    assert report.selection_coverage == 0.0
    assert report.to_api_dict()["incompleteListingIdentityCount"] == 1
