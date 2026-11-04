from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowLiveUncertaintyRepository:
    """Persist the ex-ante uncertainty artifact once per live candidate.

    The row owns a SHA-256 over canonical JSON. Reads recompute it so accidental
    or manual database edits cannot silently change the scenarios that ATHENA
    actually had available at inference time.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_live_uncertainty (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL UNIQUE,
                    candidate_fingerprint TEXT NOT NULL,
                    uncertainty_fingerprint TEXT NOT NULL UNIQUE,
                    artifact_version TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES athena_recommendation_shadow_live_candidates(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_live_uncertainty_candidate_fingerprint
                ON athena_recommendation_shadow_live_uncertainty(candidate_fingerprint);
                """
            )

    def save(
        self,
        *,
        candidate_id: int,
        candidate_fingerprint: str,
        artifact_version: str,
        artifact: dict[str, Any],
    ) -> int:
        self.initialize()
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        normalized_candidate_fingerprint = self._sha256_text(
            candidate_fingerprint, "candidate_fingerprint"
        )
        version = self._required_text(artifact_version, "artifact_version")
        artifact_json = self._canonical_json(artifact)
        uncertainty_fingerprint = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, candidate_fingerprint, uncertainty_fingerprint,
                       artifact_version, artifact_json
                FROM athena_recommendation_shadow_live_uncertainty
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["candidate_fingerprint"]) != normalized_candidate_fingerprint
                    or str(existing["uncertainty_fingerprint"]) != uncertainty_fingerprint
                    or str(existing["artifact_version"]) != version
                    or str(existing["artifact_json"]) != artifact_json
                ):
                    raise ValueError(
                        "La incertidumbre del candidato ya fue sellada con contenido distinto."
                    )
                return int(existing["id"])

            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_shadow_live_uncertainty (
                    candidate_id,
                    candidate_fingerprint,
                    uncertainty_fingerprint,
                    artifact_version,
                    artifact_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    normalized_candidate_fingerprint,
                    uncertainty_fingerprint,
                    version,
                    artifact_json,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir la incertidumbre shadow live.")
        return int(cursor.lastrowid)

    def get(self, uncertainty_id: int) -> dict[str, Any] | None:
        self.initialize()
        if isinstance(uncertainty_id, bool) or uncertainty_id <= 0:
            raise ValueError("uncertainty_id debe ser positivo.")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_uncertainty
                WHERE id = ?
                """,
                (uncertainty_id,),
            ).fetchone()
        return self._row(row)

    def get_for_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        self.initialize()
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_live_uncertainty
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
        return self._row(row)

    def _row(self, row: object) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        artifact_json = str(result.pop("artifact_json"))
        expected_fingerprint = self._sha256_text(
            result.get("uncertainty_fingerprint"), "uncertainty_fingerprint"
        )
        actual_fingerprint = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
        if expected_fingerprint != actual_fingerprint:
            raise ValueError("La incertidumbre shadow live persistida fue alterada.")
        try:
            artifact = json.loads(artifact_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("La incertidumbre persistida contiene JSON inválido.") from exc
        if not isinstance(artifact, dict):
            raise ValueError("La incertidumbre persistida no contiene un objeto JSON.")
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

    def _sha256_text(self, value: object, field: str) -> str:
        normalized = self._required_text(value, field).lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return normalized
