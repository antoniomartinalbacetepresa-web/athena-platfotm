from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import TracebackType


class AthenaConnection(sqlite3.Connection):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            result = super().__exit__(
                exc_type,
                exc_value,
                traceback,
            )
        finally:
            self.close()

        return bool(result)


class AthenaDatabase:
    SCHEMA_VERSION = 4

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else self._default_database_path()
        )

    def initialize(self) -> None:
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.connect() as connection:
            self._create_schema_metadata(
                connection
            )

            current_version = (
                self._get_schema_version(
                    connection
                )
            )

            if (
                current_version is not None
                and current_version
                > self.SCHEMA_VERSION
            ):
                raise RuntimeError(
                    "La base de datos usa una versión "
                    "de esquema más reciente que esta "
                    "versión de ATHENA TYCHE."
                )

            if (
                current_version is not None
                and current_version < 3
            ):
                self._migrate_to_v3(
                    connection
                )

            if (
                current_version is not None
                and current_version < 4
            ):
                self._migrate_to_v4(
                    connection
                )

            self._create_schema(
                connection
            )

            self._set_schema_version(
                connection
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            factory=AthenaConnection,
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA journal_mode = WAL"
        )

        return connection

    def _default_database_path(self) -> Path:
        configured_path = os.getenv(
            "ATHENA_DATABASE_PATH"
        )

        if (
            configured_path is not None
            and configured_path.strip()
        ):
            return Path(
                configured_path.strip()
            )

        project_root = (
            Path(__file__)
            .resolve()
            .parents[3]
        )

        return (
            project_root
            / "database"
            / "athena_tyche.db"
        )

    def _create_schema_metadata(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _get_schema_version(
        self,
        connection: sqlite3.Connection,
    ) -> int | None:
        row = connection.execute(
            """
            SELECT value
            FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

        if row is None:
            return None

        try:
            return int(
                row["value"]
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                "La versión del esquema almacenada "
                "no es válida."
            ) from exc

    def _table_exists(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            LIMIT 1
            """,
            (
                table_name,
            ),
        ).fetchone()

        return row is not None

    def _column_names(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        rows = connection.execute(
            f"""
            PRAGMA table_info(
                {table_name}
            )
            """
        ).fetchall()

        return {
            str(
                row["name"]
            )
            for row in rows
        }

    def _migrate_to_v3(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        if not self._table_exists(
            connection,
            "universe_import_runs",
        ):
            return

        columns = self._column_names(
            connection,
            "universe_import_runs",
        )

        required_v3_columns = {
            "inserted",
            "updated",
            "unchanged",
        }

        if required_v3_columns.issubset(
            columns
        ):
            return

        connection.execute(
            """
            ALTER TABLE universe_import_runs
            RENAME TO universe_import_runs_v2
            """
        )

        self._create_universe_import_runs_table(
            connection
        )

        connection.execute(
            """
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
                deactivated,
                reconciliation_applied,
                started_at,
                completed_at,
                error_message,
                created_at
            )
            SELECT
                id,
                source_id,
                status,
                received,
                accepted,
                rejected,
                created_or_updated,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                started_at,
                completed_at,
                error_message,
                created_at
            FROM universe_import_runs_v2
            """
        )

        connection.execute(
            """
            DROP TABLE universe_import_runs_v2
            """
        )

    def _migrate_to_v4(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        if not self._table_exists(
            connection,
            "universe_import_runs",
        ):
            return

        columns = self._column_names(
            connection,
            "universe_import_runs",
        )

        required_v4_columns = {
            "deactivated",
            "reconciliation_applied",
        }

        if required_v4_columns.issubset(
            columns
        ):
            return

        connection.execute(
            """
            ALTER TABLE universe_import_runs
            RENAME TO universe_import_runs_v3
            """
        )

        self._create_universe_import_runs_table(
            connection
        )

        connection.execute(
            """
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
                deactivated,
                reconciliation_applied,
                started_at,
                completed_at,
                error_message,
                created_at
            )
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
                NULL,
                NULL,
                started_at,
                completed_at,
                error_message,
                created_at
            FROM universe_import_runs_v3
            """
        )

        connection.execute(
            """
            DROP TABLE universe_import_runs_v3
            """
        )

    def _create_universe_import_runs_table(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS universe_import_runs (
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
                    DEFAULT 0
                    CHECK (
                        received >= 0
                    ),

                accepted INTEGER NOT NULL
                    DEFAULT 0
                    CHECK (
                        accepted >= 0
                    ),

                rejected INTEGER NOT NULL
                    DEFAULT 0
                    CHECK (
                        rejected >= 0
                    ),

                created_or_updated INTEGER NOT NULL
                    DEFAULT 0
                    CHECK (
                        created_or_updated >= 0
                    ),

                inserted INTEGER
                    CHECK (
                        inserted IS NULL
                        OR inserted >= 0
                    ),

                updated INTEGER
                    CHECK (
                        updated IS NULL
                        OR updated >= 0
                    ),

                unchanged INTEGER
                    CHECK (
                        unchanged IS NULL
                        OR unchanged >= 0
                    ),

                deactivated INTEGER
                    CHECK (
                        deactivated IS NULL
                        OR deactivated >= 0
                    ),

                reconciliation_applied INTEGER
                    CHECK (
                        reconciliation_applied IS NULL
                        OR reconciliation_applied IN (0, 1)
                    ),

                started_at TEXT NOT NULL,
                completed_at TEXT,

                error_message TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                CHECK (
                    accepted + rejected <= received
                ),

                CHECK (
                    created_or_updated <= accepted
                ),

                CHECK (
                    (
                        inserted IS NULL
                        AND updated IS NULL
                        AND unchanged IS NULL
                    )
                    OR
                    (
                        inserted IS NOT NULL
                        AND updated IS NOT NULL
                        AND unchanged IS NOT NULL
                        AND (
                            inserted
                            + updated
                            + unchanged
                            = accepted
                        )
                        AND (
                            created_or_updated
                            = inserted + updated
                        )
                    )
                )
            )
            """
        )

    def _create_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS instruments (
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

            CREATE INDEX IF NOT EXISTS
                idx_instruments_symbol
            ON instruments (
                symbol
            );

            CREATE INDEX IF NOT EXISTS
                idx_instruments_region
            ON instruments (
                region_key
            );

            CREATE INDEX IF NOT EXISTS
                idx_instruments_issuer
            ON instruments (
                issuer_id
            );

            CREATE INDEX IF NOT EXISTS
                idx_instruments_market_cap
            ON instruments (
                market_cap_usd
            );

            CREATE TABLE IF NOT EXISTS market_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                instrument_id INTEGER NOT NULL,

                observed_at TEXT NOT NULL,

                open REAL,
                high REAL,
                low REAL,
                close REAL,
                adjusted_close REAL,
                volume REAL,

                market_cap_usd REAL,

                source_provider TEXT NOT NULL,
                source_timestamp TEXT,
                retrieved_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    instrument_id
                )
                REFERENCES instruments(id)
                ON DELETE CASCADE,

                UNIQUE (
                    instrument_id,
                    observed_at,
                    source_provider
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_market_observations_instrument_time
            ON market_observations (
                instrument_id,
                observed_at
            );

            CREATE TABLE IF NOT EXISTS fx_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                currency TEXT NOT NULL,
                base_currency TEXT NOT NULL
                    DEFAULT 'USD',

                rate REAL NOT NULL
                    CHECK (
                        rate > 0
                    ),

                source_symbol TEXT,
                source_provider TEXT NOT NULL,

                source_timestamp TEXT,
                retrieved_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    currency,
                    base_currency,
                    retrieved_at,
                    source_provider
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_fx_rates_currency_time
            ON fx_rates (
                currency,
                base_currency,
                retrieved_at
            );
            """
        )

        self._create_universe_import_runs_table(
            connection
        )

        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS
                idx_universe_import_runs_source_time
            ON universe_import_runs (
                source_id,
                started_at
            );

            CREATE INDEX IF NOT EXISTS
                idx_universe_import_runs_status
            ON universe_import_runs (
                status
            );

            CREATE TABLE IF NOT EXISTS investors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,
                organization_name TEXT,

                regulator TEXT,
                regulator_identifier TEXT,

                strategy TEXT,

                is_active INTEGER NOT NULL
                    DEFAULT 1
                    CHECK (
                        is_active IN (0, 1)
                    ),

                athena_investor_score REAL
                    CHECK (
                        athena_investor_score IS NULL
                        OR (
                            athena_investor_score >= 0
                            AND athena_investor_score <= 100
                        )
                    ),

                score_updated_at TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    regulator,
                    regulator_identifier
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_investors_score
            ON investors (
                athena_investor_score
            );

            CREATE TABLE IF NOT EXISTS investor_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                investor_id INTEGER NOT NULL,

                filing_type TEXT NOT NULL,

                accession_number TEXT,

                position_date TEXT NOT NULL,
                filing_date TEXT NOT NULL,

                source_url TEXT,
                source_provider TEXT NOT NULL,

                retrieved_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    investor_id
                )
                REFERENCES investors(id)
                ON DELETE CASCADE,

                UNIQUE (
                    investor_id,
                    filing_type,
                    accession_number
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_investor_filings_dates
            ON investor_filings (
                investor_id,
                filing_date,
                position_date
            );

            CREATE TABLE IF NOT EXISTS investor_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                filing_id INTEGER NOT NULL,

                instrument_id INTEGER,

                external_identifier TEXT,
                security_name TEXT NOT NULL,

                shares REAL,
                reported_value REAL,
                reported_value_currency TEXT,

                portfolio_weight REAL,

                position_change_type TEXT,
                previous_shares REAL,
                shares_change REAL,
                shares_change_percentage REAL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    filing_id
                )
                REFERENCES investor_filings(id)
                ON DELETE CASCADE,

                FOREIGN KEY (
                    instrument_id
                )
                REFERENCES instruments(id)
                ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS
                idx_investor_positions_instrument
            ON investor_positions (
                instrument_id
            );

            CREATE INDEX IF NOT EXISTS
                idx_investor_positions_filing
            ON investor_positions (
                filing_id
            );

            CREATE TABLE IF NOT EXISTS athena_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                instrument_id INTEGER NOT NULL,

                decision_at TEXT NOT NULL,

                model_version TEXT NOT NULL,

                athena_score REAL NOT NULL
                    CHECK (
                        athena_score >= 0
                        AND athena_score <= 100
                    ),

                recommendation TEXT NOT NULL,

                confidence REAL
                    CHECK (
                        confidence IS NULL
                        OR (
                            confidence >= 0
                            AND confidence <= 1
                        )
                    ),

                thesis TEXT,

                valuation_score REAL,
                fundamental_score REAL,
                technical_score REAL,
                macro_score REAL,
                risk_score REAL,
                news_score REAL,

                smart_money_score REAL,
                smart_money_alignment TEXT,

                source_snapshot TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    instrument_id
                )
                REFERENCES instruments(id)
                ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_athena_decisions_instrument_time
            ON athena_decisions (
                instrument_id,
                decision_at
            );

            CREATE INDEX IF NOT EXISTS
                idx_athena_decisions_score
            ON athena_decisions (
                athena_score
            );

            CREATE TABLE IF NOT EXISTS decision_investor_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                decision_id INTEGER NOT NULL,
                investor_id INTEGER NOT NULL,

                filing_id INTEGER,

                signal_type TEXT NOT NULL,

                investor_score REAL,

                signal_strength REAL
                    CHECK (
                        signal_strength IS NULL
                        OR (
                            signal_strength >= 0
                            AND signal_strength <= 1
                        )
                    ),

                position_date TEXT,
                filing_date TEXT,

                observed_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    decision_id
                )
                REFERENCES athena_decisions(id)
                ON DELETE CASCADE,

                FOREIGN KEY (
                    investor_id
                )
                REFERENCES investors(id)
                ON DELETE CASCADE,

                FOREIGN KEY (
                    filing_id
                )
                REFERENCES investor_filings(id)
                ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS
                idx_decision_investor_signals_decision
            ON decision_investor_signals (
                decision_id
            );

            CREATE INDEX IF NOT EXISTS
                idx_decision_investor_signals_investor
            ON decision_investor_signals (
                investor_id
            );

            CREATE TABLE IF NOT EXISTS investment_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                decision_id INTEGER NOT NULL,

                horizon_days INTEGER NOT NULL
                    CHECK (
                        horizon_days > 0
                    ),

                entry_price REAL,
                outcome_price REAL,

                absolute_return REAL,
                benchmark_return REAL,
                excess_return REAL,

                max_drawdown REAL,

                evaluated_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    decision_id
                )
                REFERENCES athena_decisions(id)
                ON DELETE CASCADE,

                UNIQUE (
                    decision_id,
                    horizon_days
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_investment_outcomes_horizon
            ON investment_outcomes (
                horizon_days
            );

            CREATE TABLE IF NOT EXISTS investor_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                investor_id INTEGER NOT NULL,
                instrument_id INTEGER,

                filing_id INTEGER,

                horizon_days INTEGER NOT NULL
                    CHECK (
                        horizon_days > 0
                    ),

                reference_price REAL,
                outcome_price REAL,

                absolute_return REAL,
                benchmark_return REAL,
                excess_return REAL,

                evaluated_at TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (
                    investor_id
                )
                REFERENCES investors(id)
                ON DELETE CASCADE,

                FOREIGN KEY (
                    instrument_id
                )
                REFERENCES instruments(id)
                ON DELETE SET NULL,

                FOREIGN KEY (
                    filing_id
                )
                REFERENCES investor_filings(id)
                ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS
                idx_investor_outcomes_investor
            ON investor_outcomes (
                investor_id,
                horizon_days
            );
            """
        )

    def _set_schema_version(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO schema_metadata (
                key,
                value,
                updated_at
            )
            VALUES (
                'schema_version',
                ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(self.SCHEMA_VERSION),
            ),
        )
