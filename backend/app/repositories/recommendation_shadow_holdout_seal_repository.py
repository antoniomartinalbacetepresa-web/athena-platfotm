from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowHoldoutSealRepository:
    """Persist the first sufficiently mature holdout result for each research cohort."""

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
                """
            )

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
        serialized = json.dumps(
            pipeline,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
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
