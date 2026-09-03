from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.database.athena_database import AthenaDatabase


class IssuerIdentityRepository:
    """Persists canonical issuers and evidence-backed instrument links.

    This repository is intentionally additive: it does not overwrite the legacy
    ``instruments.issuer_id`` field yet. That keeps issuer-resolution work
    reversible while ATHENA validates coverage and conflict rates.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS canonical_issuers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    domicile_country TEXT,
                    region_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS issuer_external_ids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issuer_id INTEGER NOT NULL,
                    source_provider TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    evidence_confidence REAL NOT NULL
                        CHECK (
                            evidence_confidence >= 0
                            AND evidence_confidence <= 1
                        ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (issuer_id)
                        REFERENCES canonical_issuers(id)
                        ON DELETE CASCADE,
                    UNIQUE (source_provider, external_id)
                );

                CREATE TABLE IF NOT EXISTS instrument_issuer_links (
                    instrument_id INTEGER PRIMARY KEY,
                    issuer_id INTEGER NOT NULL,
                    evidence_source TEXT NOT NULL,
                    resolution_method TEXT NOT NULL,
                    confidence REAL NOT NULL
                        CHECK (confidence >= 0 AND confidence <= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id)
                        REFERENCES instruments(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (issuer_id)
                        REFERENCES canonical_issuers(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_canonical_issuers_region
                ON canonical_issuers(region_key);

                CREATE INDEX IF NOT EXISTS
                    idx_issuer_external_ids_issuer
                ON issuer_external_ids(issuer_id);

                CREATE INDEX IF NOT EXISTS
                    idx_instrument_issuer_links_issuer
                ON instrument_issuer_links(issuer_id);
                """
            )

    def upsert_external_issuer(
        self,
        *,
        source_provider: str,
        external_id: str,
        canonical_name: str,
        evidence_confidence: float,
        domicile_country: str | None = None,
        region_key: str | None = None,
    ) -> int:
        self.initialize()
        source = self._required_text(source_provider, "source_provider")
        external = self._required_text(external_id, "external_id")
        name = self._required_text(canonical_name, "canonical_name")
        confidence = self._confidence(evidence_confidence)
        country = self._optional_text(domicile_country)
        region = self._optional_text(region_key)
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT issuer_id
                FROM issuer_external_ids
                WHERE source_provider = ? AND external_id = ?
                """,
                (source, external),
            ).fetchone()

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO canonical_issuers (
                        canonical_name,
                        domicile_country,
                        region_key,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, country, region, now, now),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("No se pudo crear el emisor canónico.")
                issuer_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO issuer_external_ids (
                        issuer_id,
                        source_provider,
                        external_id,
                        evidence_confidence,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (issuer_id, source, external, confidence, now, now),
                )
                return issuer_id

            issuer_id = int(existing["issuer_id"])
            connection.execute(
                """
                UPDATE canonical_issuers
                SET
                    canonical_name = ?,
                    domicile_country = COALESCE(?, domicile_country),
                    region_key = COALESCE(?, region_key),
                    updated_at = ?
                WHERE id = ?
                """,
                (name, country, region, now, issuer_id),
            )
            connection.execute(
                """
                UPDATE issuer_external_ids
                SET evidence_confidence = ?, updated_at = ?
                WHERE source_provider = ? AND external_id = ?
                """,
                (confidence, now, source, external),
            )
            return issuer_id

    def link_instrument(
        self,
        *,
        instrument_id: int,
        issuer_id: int,
        evidence_source: str,
        resolution_method: str,
        confidence: float,
    ) -> None:
        self.initialize()
        if instrument_id <= 0 or issuer_id <= 0:
            raise ValueError("instrument_id e issuer_id deben ser positivos.")
        source = self._required_text(evidence_source, "evidence_source")
        method = self._required_text(resolution_method, "resolution_method")
        normalized_confidence = self._confidence(confidence)
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_issuer_links (
                    instrument_id,
                    issuer_id,
                    evidence_source,
                    resolution_method,
                    confidence,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id) DO UPDATE SET
                    issuer_id = excluded.issuer_id,
                    evidence_source = excluded.evidence_source,
                    resolution_method = excluded.resolution_method,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                WHERE excluded.confidence >= instrument_issuer_links.confidence
                """,
                (
                    instrument_id,
                    issuer_id,
                    source,
                    method,
                    normalized_confidence,
                    now,
                    now,
                ),
            )

    def get_issuer_for_instrument(self, instrument_id: int) -> dict[str, Any] | None:
        self.initialize()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    ci.id AS issuer_id,
                    ci.canonical_name,
                    ci.domicile_country,
                    ci.region_key,
                    iil.evidence_source,
                    iil.resolution_method,
                    iil.confidence
                FROM instrument_issuer_links iil
                JOIN canonical_issuers ci ON ci.id = iil.issuer_id
                WHERE iil.instrument_id = ?
                """,
                (instrument_id,),
            ).fetchone()

        return dict(row) if row is not None else None

    def list_external_ids(self, issuer_id: int) -> list[dict[str, Any]]:
        self.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_provider, external_id, evidence_confidence
                FROM issuer_external_ids
                WHERE issuer_id = ?
                ORDER BY source_provider, external_id
                """,
                (issuer_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _required_text(self, value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _confidence(self, value: float) -> float:
        result = float(value)
        if not isfinite(result) or result < 0 or result > 1:
            raise ValueError("confidence debe ser finita y estar entre 0 y 1.")
        return result
