from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowLiveCycleAttestationRepository:
    """Persist one immutable trusted-cycle provenance attestation per live candidate."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_live_cycle_attestations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL UNIQUE,
                    candidate_fingerprint TEXT NOT NULL UNIQUE,
                    attestation_fingerprint TEXT NOT NULL UNIQUE,
                    artifact_version TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES athena_recommendation_shadow_live_candidates(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_live_cycle_attestation_candidate_fingerprint
                ON athena_recommendation_shadow_live_cycle_attestations(candidate_fingerprint);
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
        normalized_candidate = self._sha256(candidate_fingerprint, "candidate_fingerprint")
        version = self._required_text(artifact_version, "artifact_version")
        artifact_json = self._canonical_json(artifact)
        attestation_fingerprint = hashlib.sha256(
            artifact_json.encode("utf-8")
        ).hexdigest()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, candidate_fingerprint, attestation_fingerprint,
                       artifact_version, artifact_json
                FROM athena_recommendation_shadow_live_cycle_attestations
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["candidate_fingerprint"]) != normalized_candidate
                    or str(existing["attestation_fingerprint"]) != attestation_fingerprint
                    or str(existing["artifact_version"]) != version
                    or str(existing["artifact_json"]) != artifact_json
                ):
                    raise ValueError(
                        "El candidato live ya tiene una atestación de ciclo distinta."
                    )
                return int(existing["id"])

            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_shadow_live_cycle_attestations (
                    candidate_id, candidate_fingerprint, attestation_fingerprint,
                    artifact_version, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    normalized_candidate,
                    attestation_fingerprint,
                    version,
                    artifact_json,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir la atestación del ciclo live.")
        return int(cursor.lastrowid)

    def get_for_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        self.initialize()
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_shadow_live_cycle_attestations
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
        expected = self._sha256(
            result.get("attestation_fingerprint"), "attestation_fingerprint"
        )
        actual = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
        if expected != actual:
            raise ValueError("La atestación persistida del ciclo live fue alterada.")
        try:
            artifact = json.loads(artifact_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("La atestación del ciclo contiene JSON inválido.") from exc
        if not isinstance(artifact, dict):
            raise ValueError("La atestación del ciclo no contiene un objeto JSON.")
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
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = self._required_text(value, field).lower()
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result
