from __future__ import annotations

from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.database.athena_database_legacy import AthenaDatabase as AthenaDatabaseV4
from app.repositories.corporate_action_repository import CorporateActionRepository


def _create_real_v4_database(database_path: Path) -> AthenaDatabaseV4:
    database = AthenaDatabaseV4(database_path)
    database.initialize()

    with database.connect() as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()

    assert version is not None
    assert version["value"] == "4"
    return database


def _create_v4_database_with_existing_action(database_path: Path) -> None:
    database = _create_real_v4_database(database_path)

    with database.connect() as connection:
        instrument_id = connection.execute(
            """
            INSERT INTO instruments (
                id, symbol, company_name, exchange_short_name
            ) VALUES (7, 'AAPL', 'Apple Inc.', 'NASDAQ')
            """
        ).lastrowid
        assert instrument_id == 7

        connection.executescript(
            """
            CREATE TABLE corporate_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                action_type TEXT NOT NULL
                    CHECK (action_type IN ('dividend', 'split')),
                effective_at TEXT NOT NULL,
                cash_amount REAL,
                split_ratio REAL,
                currency TEXT,
                source_provider TEXT NOT NULL,
                source_timestamp TEXT,
                retrieved_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instrument_id)
                    REFERENCES instruments(id)
                    ON DELETE CASCADE,
                CHECK (
                    (action_type = 'dividend' AND cash_amount > 0
                        AND split_ratio IS NULL)
                    OR
                    (action_type = 'split' AND split_ratio > 0
                        AND cash_amount IS NULL)
                ),
                UNIQUE (
                    instrument_id,
                    action_type,
                    effective_at,
                    source_provider,
                    retrieved_at
                )
            );

            CREATE INDEX idx_corporate_actions_instrument_effective
            ON corporate_actions (instrument_id, effective_at);

            CREATE INDEX idx_corporate_actions_pit
            ON corporate_actions (instrument_id, retrieved_at, effective_at);

            INSERT INTO corporate_actions (
                id, instrument_id, action_type, effective_at, cash_amount,
                currency, source_provider, source_timestamp, retrieved_at
            ) VALUES (
                11, 7, 'dividend', '2026-08-01T00:00:00+00:00', 0.26,
                'USD', 'yahoo', '2026-08-01T00:00:00+00:00',
                '2026-08-02T10:00:00+00:00'
            );
            """
        )


def test_fresh_database_registers_schema_v5_and_corporate_actions(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "fresh.db")
    database.initialize()

    with database.connect() as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corporate_actions'"
        ).fetchone()
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='corporate_actions'"
            ).fetchall()
        }

    assert version is not None
    assert version["value"] == "5"
    assert table is not None
    assert "idx_corporate_actions_instrument_effective" in indexes
    assert "idx_corporate_actions_pit" in indexes


def test_v4_upgrade_preserves_preexisting_corporate_action_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "v4-with-actions.db"
    _create_v4_database_with_existing_action(database_path)

    database = AthenaDatabase(database_path)
    database.initialize()

    with database.connect() as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        row = connection.execute(
            """
            SELECT id, instrument_id, action_type, cash_amount, currency,
                   source_provider, effective_at, retrieved_at
            FROM corporate_actions
            WHERE id = 11
            """
        ).fetchone()

    assert version is not None
    assert version["value"] == "5"
    assert row is not None
    assert row["instrument_id"] == 7
    assert row["action_type"] == "dividend"
    assert row["cash_amount"] == 0.26
    assert row["currency"] == "USD"
    assert row["source_provider"] == "yahoo"
    assert row["effective_at"] == "2026-08-01T00:00:00+00:00"
    assert row["retrieved_at"] == "2026-08-02T10:00:00+00:00"


def test_v4_upgrade_without_corporate_actions_creates_canonical_table(tmp_path: Path) -> None:
    database_path = tmp_path / "v4-no-actions.db"
    _create_real_v4_database(database_path)

    database = AthenaDatabase(database_path)
    database.initialize()

    with database.connect() as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corporate_actions'"
        ).fetchone()
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()

    assert table is not None
    assert version is not None
    assert version["value"] == "5"


def test_repository_operates_on_canonical_v5_schema(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "repository.db")
    database.initialize()
    repository = CorporateActionRepository(database)

    with database.connect() as connection:
        instrument_id = connection.execute(
            """
            INSERT INTO instruments (symbol, company_name, exchange_short_name)
            VALUES ('MSFT', 'Microsoft Corporation', 'NASDAQ')
            """
        ).lastrowid
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corporate_actions'"
        ).fetchone()

    assert instrument_id is not None
    assert table is not None
    assert repository is not None
