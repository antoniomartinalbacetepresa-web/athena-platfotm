from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowLiveCandidateRepository:
    """Persist shadow inference artifacts separately from real recommendations."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_live_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    candidate_fingerprint TEXT NOT NULL UNIQUE,
                    confirmation_fingerprint TEXT NOT NULL,
                    artifact_version TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (snapshot_id)
                        REFERENCES athena_recommendation_shadow_snapshots(id)
                        ON DELETE CASCADE,
                    UNIQUE (snapshot_id, confirmation_fingerprint, artifact_version)
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_live_candidates_snapshot
                ON athena_recommendation_shadow_live_candidates(snapshot_id);
                """
            )

    def save(
        self,
        *,
        snapshot_id: int,
        candidate_fingerprint: str,
        confirmation_fingerprint: str,
        artifact_version: str,
        artifact: dict[str, Any],
    ) -> int:
        self.initialize()
        if snapshot_id <= 0:
            raise ValueError("snapshot_id debe ser positivo.")
        fingerprint = self._required_text(candidate_fingerprint, "candidate_fingerprint")
        confirmation = self._required_text(
            confirmation_fingerprint, "confirmation_fingerprint"
        )
        version = self._required_text(artifact_version, "artifact_version")
        artifact_json = self._canonical_json(artifact)

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, snapshot_id, confirmation_fingerprint,
                       artifact_version, artifact_json
                FROM athena_recommendation_shadow_live_candidates
                WHERE candidate_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                if (
                    int(existing["snapshot_id"]) != snapshot_id
                    or str(existing["confirmation_fingerprint"]) != confirmation
                    or str(existing["artifact_version"]) != version
                    or str(existing["artifact_json"]) != artifact_json
                ):
                    raise ValueError(
                        "El candidate_fingerprint ya existe con contenido distinto."
                    )
                return int(existing["id"])

            existing_slot = connection.execute(
                """
                SELECT id, candidate_fingerprint, artifact_json
                FROM athena_recommendation_shadow_live_candidates
                WHERE snapshot_id = ?
                  AND confirmation_fingerprint = ?
                  AND artifact_version = ?
                """,
                (snapshot_id, confirmation, version),
            ).fetchone()
            if existing_slot is not None:
                raise ValueError(
                    "Ya existe otro candidato para el mismo snapshot y confirmación."
                )

            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_shadow_live_candidates (
                    snapshot_id,
                    candidate_fingerprint,
                    confirmation_fingerprint,
                    artifact_version,
                    artifact_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    fingerprint,
                    confirmation,
                    version,
                    artifact_json,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir el candidato live en sombra.")
        return int(cursor.lastrowid)

    def get(self, candidate_id: int) -> dict[str, Any] | None:
        self.initialize()
        if candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
        return self._row(row)

    def get_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._required_text(fingerprint, "candidate_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_candidates
                WHERE candidate_fingerprint = ?
                """,
                (normalized,),
            ).fetchone()
        return self._row(row)

    def list_for_snapshot(self, snapshot_id: int) -> list[dict[str, Any]]:
        self.initialize()
        if snapshot_id <= 0:
            raise ValueError("snapshot_id debe ser positivo.")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_candidates
                WHERE snapshot_id = ?
                ORDER BY id ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return [item for row in rows if (item := self._row(row)) is not None]

    def list_all(self) -> list[dict[str, Any]]:
        """Return every persisted shadow-live candidate in deterministic order.

        Longitudinal research needs the immutable artifacts, not an SQL-derived
        interpretation of their contents. Filtering by symbol, horizon and
        as-of therefore happens after each artifact has been revalidated by the
        service that owns its schema and fingerprint contract.
        """

        self.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_candidates
                ORDER BY id ASC
                """
            ).fetchall()
        return [item for row in rows if (item := self._row(row)) is not None]

    def _row(self, row: object) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        try:
            artifact = json.loads(str(result.pop("artifact_json")))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("El candidato live persistido contiene JSON inválido.") from exc
        if not isinstance(artifact, dict):
            raise ValueError("El candidato live persistido no contiene un objeto JSON.")
        result["artifact"] = artifact
        return result

    def _canonical_json(self, value: dict[str, Any]) -> str:
        if not isinstance(value, dict):
            raise ValueError("artifact debe ser un objeto.")
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact debe ser JSON finito y serializable.") from exc

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized
