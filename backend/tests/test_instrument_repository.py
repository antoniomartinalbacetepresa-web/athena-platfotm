from __future__ import annotations

from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import (
    InstrumentRepository,
    InstrumentUpsertStats,
)


def _create_repository(
    tmp_path: Path,
) -> InstrumentRepository:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    return InstrumentRepository(
        database=database
    )


def test_upsert_inserts_instrument(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instrument_id = repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "currency": "USD",
            "marketCap": 4_600_000_000_000,
            "marketCapLocal": 4_600_000_000_000,
            "sourceProvider": "yahoo",
        }
    )

    stored = repository.get_by_id(
        instrument_id
    )

    assert stored is not None
    assert stored["symbol"] == "AAPL"
    assert stored["company_name"] == "Apple Inc."
    assert stored["region_key"] == "america"
    assert stored["exchange_short_name"] == "NASDAQ"
    assert stored["instrument_type"] == "common_stock"
    assert stored["is_primary_listing"] == 1
    assert stored["currency"] == "USD"
    assert stored["market_cap_usd"] == 4_600_000_000_000
    assert stored["market_cap_local"] == 4_600_000_000_000
    assert stored["source_provider"] == "yahoo"


def test_upsert_same_listing_updates_without_duplicate(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    first_id = repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
            "marketCap": 4_000_000_000_000,
            "currency": "USD",
        }
    )

    second_id = repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Incorporated",
            "exchangeShortName": "NASDAQ",
            "marketCap": 4_500_000_000_000,
            "currency": "USD",
            "sector": "Technology",
        }
    )

    assert second_id == first_id
    assert repository.count() == 1

    stored = repository.get_by_id(
        first_id
    )

    assert stored is not None
    assert stored["company_name"] == "Apple Incorporated"
    assert stored["market_cap_usd"] == 4_500_000_000_000
    assert stored["sector"] == "Technology"


def test_same_symbol_different_exchange_creates_two_listings(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    first_id = repository.upsert(
        {
            "symbol": "TEST",
            "companyName": "Test Company",
            "exchangeShortName": "NYSE",
        }
    )

    second_id = repository.upsert(
        {
            "symbol": "TEST",
            "companyName": "Test Company",
            "exchangeShortName": "LSE",
        }
    )

    assert first_id != second_id
    assert repository.count() == 2


def test_get_by_listing_returns_correct_instrument(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
        }
    )

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["symbol"] == "AAPL"
    assert stored["exchange_short_name"] == "NASDAQ"


def test_get_by_listing_normalizes_symbol_and_exchange(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert(
        {
            "symbol": "aapl",
            "companyName": "Apple Inc.",
            "exchangeShortName": "nasdaq",
        }
    )

    stored = repository.get_by_listing(
        " aapl ",
        " nasdaq ",
    )

    assert stored is not None
    assert stored["symbol"] == "AAPL"
    assert stored["exchange_short_name"] == "NASDAQ"


def test_listing_without_exchange_can_be_updated(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    first_id = repository.upsert(
        {
            "symbol": "UNKNOWN",
            "companyName": "Unknown Company",
        }
    )

    second_id = repository.upsert(
        {
            "symbol": "UNKNOWN",
            "companyName": "Updated Company",
        }
    )

    assert first_id == second_id
    assert repository.count() == 1

    stored = repository.get_by_listing(
        "UNKNOWN",
        None,
    )

    assert stored is not None
    assert stored["company_name"] == "Updated Company"


def test_upsert_many_inserts_multiple_instruments(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    ids = repository.upsert_many(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "SAP.DE",
                "companyName": "SAP SE",
                "exchangeShortName": "XETRA",
            },
        ]
    )

    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert repository.count() == 3


def test_upsert_many_is_idempotent(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instruments = [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
        },
        {
            "symbol": "MSFT",
            "companyName": "Microsoft Corporation",
            "exchangeShortName": "NASDAQ",
        },
    ]

    first_ids = repository.upsert_many(
        instruments
    )

    second_ids = repository.upsert_many(
        instruments
    )

    assert second_ids == first_ids
    assert repository.count() == 2


def test_count_active_only(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert(
        {
            "symbol": "ACTIVE",
            "companyName": "Active Company",
            "exchangeShortName": "NYSE",
            "isActive": True,
        }
    )

    repository.upsert(
        {
            "symbol": "INACTIVE",
            "companyName": "Inactive Company",
            "exchangeShortName": "NYSE",
            "isActive": False,
        }
    )

    assert repository.count() == 2
    assert repository.count(
        active_only=True
    ) == 1


def test_list_active_excludes_inactive_and_orders_by_listing(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert_many(
        [
            {
                "symbol": "MSFT",
                "companyName": "Microsoft",
                "exchangeShortName": "NASDAQ",
                "isActive": True,
            },
            {
                "symbol": "AAPL",
                "companyName": "Apple",
                "exchangeShortName": "NASDAQ",
                "isActive": True,
            },
            {
                "symbol": "ZZZ",
                "companyName": "Inactive",
                "exchangeShortName": "NYSE",
                "isActive": False,
            },
        ]
    )

    rows = repository.list_active()

    assert [row["symbol"] for row in rows] == [
        "AAPL",
        "MSFT",
    ]


def test_list_active_filters_source_and_paginates(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert_many(
        [
            {
                "symbol": "AAA",
                "companyName": "A",
                "exchangeShortName": "NASDAQ",
                "sourceProvider": "nasdaq_trader",
            },
            {
                "symbol": "BBB",
                "companyName": "B",
                "exchangeShortName": "NYSE",
                "sourceProvider": "nasdaq_trader",
            },
            {
                "symbol": "CCC",
                "companyName": "C",
                "exchangeShortName": "XETRA",
                "sourceProvider": "other_source",
            },
        ]
    )

    rows = repository.list_active(
        source_provider="nasdaq_trader",
        limit=1,
        offset=1,
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BBB"
    assert rows[0]["source_provider"] == "nasdaq_trader"


def test_list_active_validates_pagination(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path)

    with pytest.raises(ValueError, match="limit"):
        repository.list_active(limit=0)

    with pytest.raises(ValueError, match="offset"):
        repository.list_active(offset=-1)


def test_upsert_normalizes_boolean_values(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instrument_id = repository.upsert(
        {
            "symbol": "BOOL",
            "companyName": "Boolean Company",
            "exchangeShortName": "NYSE",
            "isPrimaryListing": "yes",
            "isActive": "false",
        }
    )

    stored = repository.get_by_id(
        instrument_id
    )

    assert stored is not None
    assert stored["is_primary_listing"] == 1
    assert stored["is_active"] == 0


def test_upsert_normalizes_currency_to_uppercase(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instrument_id = repository.upsert(
        {
            "symbol": "SAP.DE",
            "companyName": "SAP SE",
            "exchangeShortName": "XETRA",
            "currency": "eur",
        }
    )

    stored = repository.get_by_id(
        instrument_id
    )

    assert stored is not None
    assert stored["currency"] == "EUR"
    assert stored["market_cap_local_currency"] == "EUR"


def test_invalid_market_cap_is_stored_as_null(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instrument_id = repository.upsert(
        {
            "symbol": "TEST",
            "companyName": "Test Company",
            "exchangeShortName": "NYSE",
            "marketCap": -100,
        }
    )

    stored = repository.get_by_id(
        instrument_id
    )

    assert stored is not None
    assert stored["market_cap_usd"] is None


def test_upsert_requires_symbol(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="symbol es obligatorio.",
    ):
        repository.upsert(
            {
                "symbol": "   ",
                "companyName": "Test Company",
                "exchangeShortName": "NYSE",
            }
        )


def test_upsert_requires_company_name(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="companyName es obligatorio.",
    ):
        repository.upsert(
            {
                "symbol": "TEST",
                "companyName": "",
                "exchangeShortName": "NYSE",
            }
        )


def test_get_by_id_returns_none_when_missing(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    result = repository.get_by_id(
        999999
    )

    assert result is None


def test_upsert_many_with_stats_reports_inserted(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    stats = repository.upsert_many_with_stats(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "exchangeShortName": "NASDAQ",
            },
        ]
    )

    assert isinstance(
        stats,
        InstrumentUpsertStats,
    )
    assert stats.processed == 2
    assert stats.inserted == 2
    assert stats.updated == 0
    assert stats.unchanged == 0
    assert len(stats.instrument_ids) == 2


def test_upsert_many_with_stats_reports_unchanged(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    instruments = [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
            "sourceProvider": "nasdaq_trader",
            "retrievedAt": (
                "2026-09-01T00:00:00+00:00"
            ),
        },
    ]

    repository.upsert_many_with_stats(
        instruments
    )

    stats = repository.upsert_many_with_stats(
        [
            {
                **instruments[0],
                "retrievedAt": (
                    "2026-09-01T01:00:00+00:00"
                ),
            },
        ]
    )

    assert stats.processed == 1
    assert stats.inserted == 0
    assert stats.updated == 0
    assert stats.unchanged == 1


def test_upsert_many_with_stats_reports_updated(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert_many_with_stats(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "instrumentType": "common_stock",
            },
        ]
    )

    stats = repository.upsert_many_with_stats(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Incorporated",
                "exchangeShortName": "NASDAQ",
                "instrumentType": "common_stock",
            },
        ]
    )

    assert stats.processed == 1
    assert stats.inserted == 0
    assert stats.updated == 1
    assert stats.unchanged == 0

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert (
        stored["company_name"]
        == "Apple Incorporated"
    )


def test_retrieved_at_changes_without_counting_as_updated(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert_many_with_stats(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "retrievedAt": (
                    "2026-09-01T00:00:00+00:00"
                ),
            },
        ]
    )

    stats = repository.upsert_many_with_stats(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "retrievedAt": (
                    "2026-09-01T02:00:00+00:00"
                ),
            },
        ]
    )

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stats.updated == 0
    assert stats.unchanged == 1
    assert stored is not None
    assert (
        stored["retrieved_at"]
        == "2026-09-01T02:00:00+00:00"
    )


def test_upsert_many_with_stats_reports_mixed_changes(
    tmp_path: Path,
) -> None:
    repository = _create_repository(
        tmp_path
    )

    repository.upsert_many_with_stats(
        [
            {
                "symbol": "UNCH",
                "companyName": "Unchanged Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "UPD",
                "companyName": "Old Name",
                "exchangeShortName": "NASDAQ",
            },
        ]
    )

    stats = repository.upsert_many_with_stats(
        [
            {
                "symbol": "UNCH",
                "companyName": "Unchanged Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "UPD",
                "companyName": "New Name",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "NEW",
                "companyName": "New Company",
                "exchangeShortName": "NYSE",
            },
        ]
    )

    assert stats.processed == 3
    assert stats.inserted == 1
    assert stats.updated == 1
    assert stats.unchanged == 1
