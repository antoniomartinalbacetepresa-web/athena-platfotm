from __future__ import annotations

import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


class RecommendationEconomicContractAuthority:
    """Persist and recover an exact validated research contract by fingerprint."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()
        self._validator = RecommendationShadowActionEconomicContractService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_economic_contract_authority (
                    economic_contract_fingerprint TEXT PRIMARY KEY,
                    artifact_json TEXT NOT NULL
                )
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        if self._validator.validate(artifact) is not artifact:
            raise ValueError("El validador sustituyó el contrato económico.")
        fingerprint = str(artifact["economicContractFingerprint"]).strip().lower()
        serialized = json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT artifact_json FROM athena_recommendation_economic_contract_authority WHERE economic_contract_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row is not None:
                existing = json.loads(str(row["artifact_json"]))
                self._validator.validate(existing)
                if existing != artifact:
                    raise ValueError("El contrato económico sellado es inmutable.")
                return existing
            connection.execute(
                "INSERT INTO athena_recommendation_economic_contract_authority (economic_contract_fingerprint, artifact_json) VALUES (?, ?)",
                (fingerprint, serialized),
            )
        return artifact

    def get(self, *, economic_contract_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = str(economic_contract_fingerprint or "").strip().lower()
        if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
            raise ValueError("economic_contract_fingerprint debe ser SHA-256 válido.")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT artifact_json FROM athena_recommendation_economic_contract_authority WHERE economic_contract_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            return None
        artifact = json.loads(str(row["artifact_json"]))
        self._validator.validate(artifact)
        if artifact.get("economicContractFingerprint") != fingerprint:
            raise ValueError("El contrato persistido no corresponde al fingerprint solicitado.")
        return artifact
