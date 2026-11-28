from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowHoldoutSealRepository:
    """Persist immutable holdout seals and the lineage of holdout experiments."""

    EXPERIMENT_FAMILY = "shadow-ridge-excess-return-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_holdout_seals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_gate_fingerprint TEXT NOT NULL,
                    research_cutoff TEXT NOT NULL,
                    sealed_at TEXT NOT NULL,
                    pipeline_fingerprint TEXT NOT NULL,
                    pipeline_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(research_gate_fingerprint, research_cutoff)
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_holdout_seal_cutoff
                ON athena_recommendation_shadow_holdout_seals(research_cutoff);

                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_holdout_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_family TEXT NOT NULL,
                    research_gate_fingerprint TEXT NOT NULL,
                    research_cutoff TEXT NOT NULL,
                    first_attempted_at TEXT NOT NULL,
                    first_pipeline_fingerprint TEXT,
                    first_pipeline_json TEXT,
                    lineage_status TEXT NOT NULL DEFAULT 'captured_at_first_exposure',
                    created_at TEXT NOT NULL,
                    UNIQUE(experiment_family, research_gate_fingerprint, research_cutoff)
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_holdout_attempt_family
                ON athena_recommendation_shadow_holdout_attempts(experiment_family);
                """
            )
            self._migrate_attempt_columns(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_holdout_attempts (
                    experiment_family,
                    research_gate_fingerprint,
                    research_cutoff,
                    first_attempted_at,
                    first_pipeline_fingerprint,
                    first_pipeline_json,
                    lineage_status,
                    created_at
                )
                SELECT ?, research_gate_fingerprint, research_cutoff, sealed_at,
                       pipeline_fingerprint, pipeline_json, 'recovered_from_immutable_seal',
                       created_at
                FROM athena_recommendation_shadow_holdout_seals
                """,
                (self.EXPERIMENT_FAMILY,),
            )
            connection.execute(
                """
                UPDATE athena_recommendation_shadow_holdout_attempts
                SET first_pipeline_fingerprint = (
                        SELECT s.pipeline_fingerprint
                        FROM athena_recommendation_shadow_holdout_seals s
                        WHERE s.research_gate_fingerprint =
                              athena_recommendation_shadow_holdout_attempts.research_gate_fingerprint
                          AND s.research_cutoff =
                              athena_recommendation_shadow_holdout_attempts.research_cutoff
                    ),
                    first_pipeline_json = (
                        SELECT s.pipeline_json
                        FROM athena_recommendation_shadow_holdout_seals s
                        WHERE s.research_gate_fingerprint =
                              athena_recommendation_shadow_holdout_attempts.research_gate_fingerprint
                          AND s.research_cutoff =
                              athena_recommendation_shadow_holdout_attempts.research_cutoff
                    ),
                    lineage_status = 'recovered_from_immutable_seal'
                WHERE first_pipeline_json IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM athena_recommendation_shadow_holdout_seals s
                      WHERE s.research_gate_fingerprint =
                            athena_recommendation_shadow_holdout_attempts.research_gate_fingerprint
                        AND s.research_cutoff =
                            athena_recommendation_shadow_holdout_attempts.research_cutoff
                        AND s.sealed_at =
                            athena_recommendation_shadow_holdout_attempts.first_attempted_at
                  )
                """
            )
            connection.execute(
                """
                UPDATE athena_recommendation_shadow_holdout_attempts
                SET lineage_status = 'legacy_exposure_payload_unavailable'
                WHERE first_pipeline_json IS NULL
                  AND lineage_status = 'captured_at_first_exposure'
                """
            )

    def register_attempt(
        self,
        *,
        pipeline: dict[str, Any],
        attempted_at: datetime,
    ) -> dict[str, Any]:
        """Register exactly what was first exposed for one independent holdout cohort."""
        self.initialize()
        gate = self._sha256(
            pipeline.get("researchGateFingerprint"), "researchGateFingerprint"
        )
        cutoff = self._aware_iso(pipeline.get("researchCutoff"), "researchCutoff")
        attempted = self._aware_datetime(attempted_at, "attempted_at").isoformat()
        serialized = self._serialize(pipeline)
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_holdout_attempts (
                    experiment_family,
                    research_gate_fingerprint,
                    research_cutoff,
                    first_attempted_at,
                    first_pipeline_fingerprint,
                    first_pipeline_json,
                    lineage_status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'captured_at_first_exposure', ?)
                """,
                (
                    self.EXPERIMENT_FAMILY,
                    gate,
                    cutoff,
                    attempted,
                    fingerprint,
                    serialized,
                    created,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_holdout_attempts
                WHERE experiment_family = ?
                  AND research_gate_fingerprint = ?
                  AND research_cutoff = ?
                """,
                (self.EXPERIMENT_FAMILY, gate, cutoff),
            ).fetchone()
        result = self._attempt_row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar el intento holdout registrado.")
        return result

    def multiplicity_summary(self) -> dict[str, Any]:
        self.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, research_gate_fingerprint, research_cutoff,
                       first_attempted_at, first_pipeline_fingerprint,
                       first_pipeline_json, lineage_status, created_at
                FROM athena_recommendation_shadow_holdout_attempts
                WHERE experiment_family = ?
                ORDER BY first_attempted_at ASC, id ASC
                """,
                (self.EXPERIMENT_FAMILY,),
            ).fetchall()
        experiments = [self._attempt_row(row) for row in rows]
        clean = [experiment for experiment in experiments if experiment is not None]
        count = len(clean)
        complete_lineage = all(
            experiment.get("first_pipeline_fingerprint") is not None for experiment in clean
        )
        return {
            "experimentFamily": self.EXPERIMENT_FAMILY,
            "distinctHoldoutExperimentCount": count,
            "multiplicityPresent": count > 1,
            "multiplicityControlled": count <= 1,
            "correctionMethod": "not_required" if count <= 1 else "not_yet_implemented",
            "firstExposureLineageComplete": complete_lineage,
            "experiments": clean,
        }

    def get(
        self,
        *,
        research_gate_fingerprint: str,
        research_cutoff: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        gate = self._sha256(research_gate_fingerprint, "research_gate_fingerprint")
        cutoff = self._aware_iso(research_cutoff, "research_cutoff")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_holdout_seals
                WHERE research_gate_fingerprint = ? AND research_cutoff = ?
                """,
                (gate, cutoff),
            ).fetchone()
        return self._row(row)

    def seal(self, *, pipeline: dict[str, Any], sealed_at: datetime) -> dict[str, Any]:
        self.initialize()
        gate = self._sha256(
            pipeline.get("researchGateFingerprint"), "researchGateFingerprint"
        )
        cutoff = self._aware_iso(pipeline.get("researchCutoff"), "researchCutoff")
        sealed = self._aware_datetime(sealed_at, "sealed_at").isoformat()
        serialized = self._serialize(pipeline)
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_holdout_seals (
                    research_gate_fingerprint,
                    research_cutoff,
                    sealed_at,
                    pipeline_fingerprint,
                    pipeline_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (gate, cutoff, sealed, fingerprint, serialized, created),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_holdout_seals
                WHERE research_gate_fingerprint = ? AND research_cutoff = ?
                """,
                (gate, cutoff),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar el holdout sellado.")
        return result

    def _migrate_attempt_columns(self, connection: Any) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(athena_recommendation_shadow_holdout_attempts)"
            ).fetchall()
        }
        additions = {
            "first_pipeline_fingerprint": "TEXT",
            "first_pipeline_json": "TEXT",
            "lineage_status": "TEXT NOT NULL DEFAULT 'captured_at_first_exposure'",
        }
        for column, declaration in additions.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE athena_recommendation_shadow_holdout_attempts "
                    f"ADD COLUMN {column} {declaration}"
                )

    def _attempt_row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        payload = result.pop("first_pipeline_json", None)
        fingerprint = result.get("first_pipeline_fingerprint")
        if payload is None:
            result["firstPipeline"] = None
            return result
        actual = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
        if actual != fingerprint:
            raise ValueError("La primera exposición holdout no supera la verificación de integridad.")
        result["firstPipeline"] = json.loads(str(payload))
        return result

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        pipeline_json = str(result.pop("pipeline_json"))
        fingerprint = hashlib.sha256(pipeline_json.encode("utf-8")).hexdigest()
        if fingerprint != result.get("pipeline_fingerprint"):
            raise ValueError("El holdout sellado no supera la verificación de integridad.")
        result["pipeline"] = json.loads(pipeline_json)
        return result

    def _serialize(self, payload: dict[str, Any]) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return normalized

    def _aware_iso(self, value: object, field: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_datetime(parsed, field).isoformat()

    def _aware_datetime(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
