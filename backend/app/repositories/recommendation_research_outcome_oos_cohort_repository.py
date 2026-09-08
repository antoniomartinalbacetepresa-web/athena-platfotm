from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_outcome_oos_cohort_service import (
    RecommendationResearchOutcomeOosCohortService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchOutcomeOosCohortRepository:
    """Append-only, tamper-evident storage for longitudinal OOS research cohorts."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationResearchOutcomeOosCohortService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationResearchOutcomeOosCohortService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_outcome_oos_cohorts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cohort_id TEXT NOT NULL UNIQUE,
                    cohort_hash TEXT NOT NULL UNIQUE,
                    as_of TEXT NOT NULL,
                    observation_count INTEGER NOT NULL,
                    distinct_resolved_issuer_count INTEGER NOT NULL,
                    horizon_count INTEGER NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_outcome_oos_cohort_as_of
                ON athena_research_outcome_oos_cohorts(as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        cohort_id = self._text(validated.get("cohortId"), "cohortId")
        cohort_hash = self._sha256(validated.get("cohortHash"), "cohortHash")
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing_id = connection.execute(
                "SELECT * FROM athena_research_outcome_oos_cohorts WHERE cohort_id = ?",
                (cohort_id,),
            ).fetchone()
            if existing_id is not None:
                record = self._row(existing_id)
                if record["cohort_hash"] != cohort_hash:
                    raise ValueError("cohortId ya existe con contenido distinto; la cohorte es inmutable.")
                return self.validate_record(record)

            existing_hash = connection.execute(
                "SELECT * FROM athena_research_outcome_oos_cohorts WHERE cohort_hash = ?",
                (cohort_hash,),
            ).fetchone()
            if existing_hash is not None:
                raise ValueError("cohortHash ya está persistido con otra identidad.")

            connection.execute(
                """
                INSERT INTO athena_research_outcome_oos_cohorts (
                    cohort_id, cohort_hash, as_of, observation_count,
                    distinct_resolved_issuer_count, horizon_count, artifact_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cohort_id,
                    cohort_hash,
                    validated["asOf"],
                    validated["observationCount"],
                    validated["distinctResolvedIssuerCount"],
                    validated["horizonCount"],
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_outcome_oos_cohorts WHERE cohort_hash = ?",
                (cohort_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, cohort_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(cohort_hash, "cohort_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_outcome_oos_cohorts WHERE cohort_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe una OOS cohort con ese cohortHash.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("Registro OOS cohort inválido.")
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro OOS cohort carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        expected = {
            "cohort_id": validated["cohortId"],
            "cohort_hash": validated["cohortHash"],
            "as_of": validated["asOf"],
            "observation_count": validated["observationCount"],
            "distinct_resolved_issuer_count": validated["distinctResolvedIssuerCount"],
            "horizon_count": validated["horizonCount"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact canónico.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar OOS cohort persistida.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de OOS cohort no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "cohort_id": str(row["cohort_id"]),
            "cohort_hash": str(row["cohort_hash"]),
            "as_of": str(row["as_of"]),
            "observation_count": int(row["observation_count"]),
            "distinct_resolved_issuer_count": int(row["distinct_resolved_issuer_count"]),
            "horizon_count": int(row["horizon_count"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text
