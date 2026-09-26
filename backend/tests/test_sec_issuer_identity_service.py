from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.sec_issuer_identity_service import SecIssuerIdentityService


class FakeSecProvider:
    def __init__(self, associations: list[dict[str, str]]) -> None:
        self.associations = associations

    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        return self.associations


def _insert_listing(
    repository: InstrumentRepository,
    *,
    symbol: str,
    country: str = "United States",
) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Listing",
            "country": country,
            "regionKey": "america" if country == "United States" else "europe",
            "exchangeShortName": "NMS",
            "marketCap": 100.0,
        }
    )


def test_service_links_exact_unique_sec_ticker_to_canonical_issuer(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    aapl_id = _insert_listing(instruments, symbol="AAPL")

    report = SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider(
            [
                {
                    "cik": "0000320193",
                    "name": "Apple Inc.",
                    "ticker": "AAPL",
                    "exchange": "Nasdaq",
                }
            ]
        ),
    ).apply()

    assert report.eligible_listing_count == 1
    assert report.linked_listing_count == 1
    assert report.ambiguous_listing_count == 0
    assert report.unmatched_listing_count == 0
    assert report.unique_issuer_count == 1
    assert report.coverage == pytest.approx(1.0)

    identity = IssuerIdentityRepository(database=database).get_issuer_for_instrument(
        aapl_id
    )
    assert identity is not None
    assert identity["canonical_name"] == "Apple Inc."
    assert identity["domicile_country"] is None
    assert identity["region_key"] is None
    assert identity["confidence"] == pytest.approx(0.95)


def test_service_unifies_share_classes_with_same_cik(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    class_a = _insert_listing(instruments, symbol="GOOGL")
    class_c = _insert_listing(instruments, symbol="GOOG")

    report = SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider(
            [
                {
                    "cik": "0001652044",
                    "name": "Alphabet Inc.",
                    "ticker": "GOOGL",
                    "exchange": "Nasdaq",
                },
                {
                    "cik": "0001652044",
                    "name": "Alphabet Inc.",
                    "ticker": "GOOG",
                    "exchange": "Nasdaq",
                },
            ]
        ),
    ).apply()

    assert report.linked_listing_count == 2
    assert report.unique_issuer_count == 1

    identity_repository = IssuerIdentityRepository(database=database)
    first = identity_repository.get_issuer_for_instrument(class_a)
    second = identity_repository.get_issuer_for_instrument(class_c)
    assert first is not None
    assert second is not None
    assert first["issuer_id"] == second["issuer_id"]


def test_service_does_not_link_ambiguous_or_unmatched_tickers(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    ambiguous_id = _insert_listing(instruments, symbol="DUP")
    unmatched_id = _insert_listing(instruments, symbol="MISS")

    report = SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider(
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
        ),
    ).apply()

    assert report.linked_listing_count == 0
    assert report.ambiguous_listing_count == 1
    assert report.unmatched_listing_count == 1
    identity_repository = IssuerIdentityRepository(database=database)
    assert identity_repository.get_issuer_for_instrument(ambiguous_id) is None
    assert identity_repository.get_issuer_for_instrument(unmatched_id) is None


def test_service_ignores_non_us_venue_rows(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    _insert_listing(instruments, symbol="SAP.DE", country="Germany")

    report = SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider([]),
    ).apply()

    assert report.eligible_listing_count == 0
    assert report.coverage == pytest.approx(0.0)
