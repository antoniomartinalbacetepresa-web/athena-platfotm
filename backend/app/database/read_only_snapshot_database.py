"""Read-only ATHENA adapter for immutable operational evidence snapshots.

The normal AthenaDatabase.initialize() updates schema_metadata even for an
up-to-date database. Diagnostics must never modify the consistent copy whose
SHA-256 is recorded in the exported evidence.
"""

from __future__ import annotations

import sqlite3

from app.database.athena_database import AthenaConnection, AthenaDatabase


class ReadOnlySnapshotDatabase(AthenaDatabase):
    """Validate a current schema and query it without migrations or writes."""

    def connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError("Consistent SQLite snapshot does not exist")
        connection = sqlite3.connect(
            self.database_path.resolve().as_uri() + "?mode=ro",
            uri=True,
            factory=AthenaConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        return connection

    def initialize(self) -> None:
        # Never call super().initialize(): it runs DDL and writes the schema
        # version even when no migration is needed.
        with self.connect() as connection:
            if self._get_schema_version(connection) != self.SCHEMA_VERSION:
                raise RuntimeError(
                    "Snapshot schema version is not current; migrate an authorized copy first"
                )
            for table in ("instruments", "market_observations", "corporate_actions"):
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1")
