from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.instrument_type_market_cap_service import (
    InstrumentTypeMarketCapService,
)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def test_instrument_type_market_cap_report_separates_equity_non_equity_and_unknown(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                market_cap_usd,
                is_active
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            [
                ("AAA", "AAA Corp", "NMS", "common_stock", 600.0),
                ("BBB", "BBB ADR", "NYSE", "adr", 200.0),
                ("ETF1", "ETF One", "ARCX", "etf", 100.0),
                ("FUND1", "Fund One", "MUTF", "fund", 50.0),
                ("UNK", "Unknown", "OTC", "unknown", 50.0),
            ],
        )

    report = InstrumentTypeMarketCapService(database=database).get_report()

    assert report.listing_count == 5
    assert report.total_market_cap_usd == pytest.approx(1000.0)
    assert report.equity_like_market_cap_usd == pytest.approx(800.0)
    assert report.non_equity_market_cap_usd == pytest.approx(150.0)
    assert report.unknown_market_cap_usd == pytest.approx(50.0)
    assert report.equity_like_market_cap_share == pytest.approx(0.80)
    assert report.non_equity_market_cap_share == pytest.approx(0.15)
    assert report.unknown_market_cap_share == pytest.approx(0.05)
    assert report.by_type["common_stock"]["listingCount"] == 1
    assert report.by_type["etf"]["marketCapShare"] == pytest.approx(0.10)


def test_instrument_type_market_cap_report_ignores_inactive_and_missing_caps(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                market_cap_usd,
                is_active
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("ACTIVE", "Active", "NMS", "common_stock", 100.0, 1),
                ("INACTIVE", "Inactive", "NYSE", "common_stock", 900.0, 0),
                ("NO_CAP", "No Cap", "OTC", "unknown", None, 1),
            ],
        )

    report = InstrumentTypeMarketCapService(database=database).get_report()

    assert report.listing_count == 1
    assert report.total_market_cap_usd == pytest.approx(100.0)
    assert report.equity_like_market_cap_share == pytest.approx(1.0)
    assert report.non_equity_market_cap_share == pytest.approx(0.0)
    assert report.unknown_market_cap_share == pytest.approx(0.0)
