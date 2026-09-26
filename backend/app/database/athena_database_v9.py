from __future__ import annotations

import sqlite3

from app.database.athena_database_v8 import AthenaConnection, AthenaDatabase as _V8AthenaDatabase


class AthenaDatabase(_V8AthenaDatabase):
    """Schema v9 adds aggregate dividends paid to comparable issuer periods."""

    SCHEMA_VERSION = 9

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        super()._create_schema(connection)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(financial_periods)").fetchall()}
        if "dividends_paid" not in columns:
            connection.execute("ALTER TABLE financial_periods ADD COLUMN dividends_paid REAL CHECK (dividends_paid >= 0)")


__all__ = ["AthenaConnection", "AthenaDatabase"]
