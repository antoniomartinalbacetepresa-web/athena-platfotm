from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase


def _table_names(
    connection: sqlite3.Connection,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()

    return {
        str(row["name"])
        for row in rows
    }


def test_initialize_creates_database_file(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "athena_test.db"
    )

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    assert database_path.exists()
    assert database_path.is_file()


def test_initialize_creates_expected_tables(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        tables = _table_names(
            connection
        )

    expected_tables = {
        "schema_metadata",
        "instruments",
        "market_observations",
        "fx_rates",
        "universe_import_runs",
        "investors",
        "investor_filings",
        "investor_positions",
        "athena_decisions",
        "decision_investor_signals",
        "investment_outcomes",
        "investor_outcomes",
    }

    assert expected_tables.issubset(
        tables
    )


def test_initialize_registers_schema_version(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

    assert row is not None
    assert row["value"] == str(
        AthenaDatabase.SCHEMA_VERSION
    )


def test_initialize_is_idempotent(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

    assert row is not None
    assert row["total"] == 1


def test_foreign_keys_are_enabled(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        row = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()

    assert row is not None
    assert row[0] == 1


def test_universe_import_run_accepts_valid_status(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO universe_import_runs (
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "nasdaq_trader",
                "succeeded",
                13141,
                13141,
                0,
                13141,
                "2026-08-31T10:00:00+00:00",
                "2026-08-31T10:01:00+00:00",
            ),
        )

        row = connection.execute(
            """
            SELECT
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated
            FROM universe_import_runs
            """
        ).fetchone()

    assert row is not None
    assert row["source_id"] == "nasdaq_trader"
    assert row["status"] == "succeeded"
    assert row["received"] == 13141
    assert row["accepted"] == 13141
    assert row["rejected"] == 0
    assert row["created_or_updated"] == 13141


def test_universe_import_run_rejects_invalid_status(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    started_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "invalid",
                    "2026-08-31T10:00:00+00:00",
                ),
            )


def test_universe_import_run_rejects_negative_counts(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    received,
                    started_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "failed",
                    -1,
                    "2026-08-31T10:00:00+00:00",
                ),
            )


def test_instrument_unique_listing_is_enforced(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "AAPL",
                "Apple Inc.",
                "NASDAQ",
            ),
        )

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO instruments (
                    symbol,
                    company_name,
                    exchange_short_name
                )
                VALUES (?, ?, ?)
                """,
                (
                    "AAPL",
                    "Apple Inc.",
                    "NASDAQ",
                ),
            )


def test_same_symbol_can_exist_on_different_listings(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "TEST",
                "Test Company",
                "NYSE",
            ),
        )

        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "TEST",
                "Test Company",
                "LSE",
            ),
        )

        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM instruments
            WHERE symbol = 'TEST'
            """
        ).fetchone()

    assert row is not None
    assert row["total"] == 2


def test_investor_score_rejects_values_above_100(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO investors (
                    name,
                    regulator,
                    regulator_identifier,
                    athena_investor_score
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "Test Investor",
                    "SEC",
                    "123456",
                    101.0,
                ),
            )


def test_athena_score_rejects_values_below_zero(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "AAPL",
                "Apple Inc.",
                "NASDAQ",
            ),
        )

        instrument_id = cursor.lastrowid

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO athena_decisions (
                    instrument_id,
                    decision_at,
                    model_version,
                    athena_score,
                    recommendation
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    "2026-08-30T13:00:00+00:00",
                    "v1",
                    -1.0,
                    "avoid",
                ),
            )


def test_outcome_requires_positive_horizon(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        instrument_cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "AAPL",
                "Apple Inc.",
                "NASDAQ",
            ),
        )

        instrument_id = (
            instrument_cursor.lastrowid
        )

        decision_cursor = connection.execute(
            """
            INSERT INTO athena_decisions (
                instrument_id,
                decision_at,
                model_version,
                athena_score,
                recommendation
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                "2026-08-30T13:00:00+00:00",
                "v1",
                80.0,
                "buy",
            ),
        )

        decision_id = (
            decision_cursor.lastrowid
        )

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO investment_outcomes (
                    decision_id,
                    horizon_days,
                    evaluated_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    decision_id,
                    0,
                    "2026-08-30T13:00:00+00:00",
                ),
            )


def test_deleting_instrument_cascades_market_observations(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            )
            VALUES (?, ?, ?)
            """,
            (
                "AAPL",
                "Apple Inc.",
                "NASDAQ",
            ),
        )

        instrument_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id,
                observed_at,
                close,
                source_provider,
                retrieved_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                "2026-08-30T13:00:00+00:00",
                319.70,
                "yahoo",
                "2026-08-30T13:01:00+00:00",
            ),
        )

        connection.execute(
            """
            DELETE FROM instruments
            WHERE id = ?
            """,
            (
                instrument_id,
            ),
        )

        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM market_observations
            """
        ).fetchone()

    assert row is not None
    assert row["total"] == 0


def test_default_path_can_be_overridden_by_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configured_path = (
        tmp_path
        / "custom"
        / "athena.db"
    )

    monkeypatch.setenv(
        "ATHENA_DATABASE_PATH",
        str(configured_path),
    )

    database = AthenaDatabase()

    assert (
        database.database_path
        == configured_path
    )


def test_initialize_upgrades_v1_database_without_losing_instruments(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "athena_v1.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_metadata (
                key,
                value
            )
            VALUES (
                'schema_version',
                '1'
            );

            CREATE TABLE instruments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                symbol TEXT NOT NULL,
                company_name TEXT NOT NULL,

                issuer_id TEXT,
                instrument_id TEXT,

                country TEXT,
                region_key TEXT,

                exchange TEXT,
                exchange_short_name TEXT,

                instrument_type TEXT NOT NULL
                    DEFAULT 'unknown',

                is_primary_listing INTEGER NOT NULL
                    DEFAULT 0
                    CHECK (
                        is_primary_listing IN (0, 1)
                    ),

                sector TEXT,
                industry TEXT,

                currency TEXT,

                market_cap_usd REAL,
                market_cap_local REAL,
                market_cap_local_currency TEXT,

                source_provider TEXT,
                source_timestamp TEXT,
                retrieved_at TEXT,

                is_active INTEGER NOT NULL
                    DEFAULT 1
                    CHECK (
                        is_active IN (0, 1)
                    ),

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    symbol,
                    exchange_short_name
                )
            );

            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                source_provider
            )
            VALUES
                (
                    'AAPL',
                    'Apple Inc.',
                    'NASDAQ',
                    'common_stock',
                    'nasdaq_trader'
                ),
                (
                    'MSFT',
                    'Microsoft Corporation',
                    'NASDAQ',
                    'common_stock',
                    'nasdaq_trader'
                );
            """
        )

        connection.commit()
    finally:
        connection.close()

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        version_row = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

        instrument_rows = connection.execute(
            """
            SELECT
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                source_provider
            FROM instruments
            ORDER BY symbol
            """
        ).fetchall()

        import_runs_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'universe_import_runs'
            """
        ).fetchone()

    assert version_row is not None
    assert version_row["value"] == "4"

    assert len(instrument_rows) == 2

    assert instrument_rows[0]["symbol"] == "AAPL"
    assert instrument_rows[0]["company_name"] == "Apple Inc."
    assert instrument_rows[0]["exchange_short_name"] == "NASDAQ"
    assert instrument_rows[0]["instrument_type"] == "common_stock"
    assert instrument_rows[0]["source_provider"] == "nasdaq_trader"

    assert instrument_rows[1]["symbol"] == "MSFT"
    assert instrument_rows[1]["company_name"] == "Microsoft Corporation"
    assert instrument_rows[1]["exchange_short_name"] == "NASDAQ"
    assert instrument_rows[1]["instrument_type"] == "common_stock"
    assert instrument_rows[1]["source_provider"] == "nasdaq_trader"

    assert import_runs_table is not None


def test_new_database_has_import_change_columns(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            """
            PRAGMA table_info(
                universe_import_runs
            )
            """
        ).fetchall()

    columns = {
        str(row["name"]): row
        for row in rows
    }

    assert "inserted" in columns
    assert "updated" in columns
    assert "unchanged" in columns


def test_new_import_run_accepts_real_change_statistics(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO universe_import_runs (
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                inserted,
                updated,
                unchanged,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "nasdaq_trader",
                "succeeded",
                100,
                98,
                2,
                15,
                12,
                3,
                83,
                "2026-09-01T10:00:00+00:00",
                "2026-09-01T10:01:00+00:00",
            ),
        )

        row = connection.execute(
            """
            SELECT
                created_or_updated,
                inserted,
                updated,
                unchanged
            FROM universe_import_runs
            """
        ).fetchone()

    assert row is not None
    assert row["created_or_updated"] == 15
    assert row["inserted"] == 12
    assert row["updated"] == 3
    assert row["unchanged"] == 83


def test_new_import_run_rejects_inconsistent_change_statistics(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    received,
                    accepted,
                    rejected,
                    created_or_updated,
                    inserted,
                    updated,
                    unchanged,
                    started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "succeeded",
                    100,
                    100,
                    0,
                    10,
                    8,
                    2,
                    50,
                    "2026-09-01T10:00:00+00:00",
                ),
            )


def test_new_import_run_rejects_created_or_updated_mismatch(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    received,
                    accepted,
                    rejected,
                    created_or_updated,
                    inserted,
                    updated,
                    unchanged,
                    started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "succeeded",
                    100,
                    100,
                    0,
                    11,
                    8,
                    2,
                    90,
                    "2026-09-01T10:00:00+00:00",
                ),
            )


def test_initialize_upgrades_v2_import_runs_without_inventing_stats(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "athena_v2.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_metadata (
                key,
                value
            )
            VALUES (
                'schema_version',
                '2'
            );

            CREATE TABLE universe_import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_id TEXT NOT NULL,

                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'running',
                            'succeeded',
                            'failed'
                        )
                    ),

                received INTEGER NOT NULL
                    DEFAULT 0,

                accepted INTEGER NOT NULL
                    DEFAULT 0,

                rejected INTEGER NOT NULL
                    DEFAULT 0,

                created_or_updated INTEGER NOT NULL
                    DEFAULT 0,

                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO universe_import_runs (
                id,
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                started_at,
                completed_at
            )
            VALUES (
                18,
                'nasdaq_trader',
                'succeeded',
                13144,
                13144,
                0,
                13144,
                '2026-08-31T22:40:15.392246+00:00',
                '2026-08-31T22:40:17.292832+00:00'
            );
            """
        )

        connection.commit()
    finally:
        connection.close()

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        version_row = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

        run = connection.execute(
            """
            SELECT
                id,
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                inserted,
                updated,
                unchanged,
                started_at,
                completed_at
            FROM universe_import_runs
            WHERE id = 18
            """
        ).fetchone()

    assert version_row is not None
    assert version_row["value"] == "4"

    assert run is not None

    assert run["id"] == 18
    assert run["source_id"] == "nasdaq_trader"
    assert run["status"] == "succeeded"

    assert run["received"] == 13144
    assert run["accepted"] == 13144
    assert run["rejected"] == 0
    assert run["created_or_updated"] == 13144

    assert run["inserted"] is None
    assert run["updated"] is None
    assert run["unchanged"] is None

    assert (
        run["started_at"]
        == "2026-08-31T22:40:15.392246+00:00"
    )

    assert (
        run["completed_at"]
        == "2026-08-31T22:40:17.292832+00:00"
    )



def test_new_database_has_reconciliation_audit_columns(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            """
            PRAGMA table_info(
                universe_import_runs
            )
            """
        ).fetchall()

    columns = {
        str(row["name"]): row
        for row in rows
    }

    assert "deactivated" in columns
    assert "reconciliation_applied" in columns


def test_new_import_run_accepts_reconciliation_statistics(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO universe_import_runs (
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                inserted,
                updated,
                unchanged,
                deactivated,
                reconciliation_applied,
                started_at,
                completed_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "nasdaq_trader",
                "succeeded",
                100,
                95,
                5,
                3,
                2,
                1,
                92,
                4,
                1,
                "2026-09-01T10:00:00+00:00",
                "2026-09-01T10:01:00+00:00",
            ),
        )

        row = connection.execute(
            """
            SELECT
                deactivated,
                reconciliation_applied
            FROM universe_import_runs
            """
        ).fetchone()

    assert row is not None
    assert row["deactivated"] == 4
    assert row["reconciliation_applied"] == 1


def test_new_import_run_rejects_negative_deactivated(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    deactivated,
                    started_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "succeeded",
                    -1,
                    "2026-09-01T10:00:00+00:00",
                ),
            )


def test_new_import_run_rejects_invalid_reconciliation_flag(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    with database.connect() as connection:
        with pytest.raises(
            sqlite3.IntegrityError
        ):
            connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    reconciliation_applied,
                    started_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "nasdaq_trader",
                    "succeeded",
                    2,
                    "2026-09-01T10:00:00+00:00",
                ),
            )


def test_initialize_upgrades_v3_import_runs_without_inventing_reconciliation(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "athena_v3.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_metadata (
                key,
                value
            )
            VALUES (
                'schema_version',
                '3'
            );

            CREATE TABLE universe_import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_id TEXT NOT NULL,
                status TEXT NOT NULL,

                received INTEGER NOT NULL
                    DEFAULT 0,

                accepted INTEGER NOT NULL
                    DEFAULT 0,

                rejected INTEGER NOT NULL
                    DEFAULT 0,

                created_or_updated INTEGER NOT NULL
                    DEFAULT 0,

                inserted INTEGER,
                updated INTEGER,
                unchanged INTEGER,

                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO universe_import_runs (
                id,
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                inserted,
                updated,
                unchanged,
                started_at,
                completed_at
            )
            VALUES (
                19,
                'nasdaq_trader',
                'succeeded',
                13144,
                13144,
                0,
                0,
                0,
                0,
                13144,
                '2026-08-31T23:10:05.979374+00:00',
                '2026-08-31T23:10:09.857353+00:00'
            );
            """
        )

        connection.commit()
    finally:
        connection.close()

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        version_row = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

        run = connection.execute(
            """
            SELECT
                id,
                source_id,
                received,
                accepted,
                rejected,
                created_or_updated,
                inserted,
                updated,
                unchanged,
                deactivated,
                reconciliation_applied,
                started_at,
                completed_at
            FROM universe_import_runs
            WHERE id = 19
            """
        ).fetchone()

    assert version_row is not None
    assert version_row["value"] == "4"

    assert run is not None
    assert run["id"] == 19
    assert run["source_id"] == "nasdaq_trader"

    assert run["received"] == 13144
    assert run["accepted"] == 13144
    assert run["rejected"] == 0

    assert run["created_or_updated"] == 0
    assert run["inserted"] == 0
    assert run["updated"] == 0
    assert run["unchanged"] == 13144

    assert run["deactivated"] is None
    assert run["reconciliation_applied"] is None

    assert (
        run["started_at"]
        == "2026-08-31T23:10:05.979374+00:00"
    )

    assert (
        run["completed_at"]
        == "2026-08-31T23:10:09.857353+00:00"
    )

