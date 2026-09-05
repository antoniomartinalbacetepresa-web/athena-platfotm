from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationUncertaintyBoundActionCandidateRepository:
    """Append-only authority for uncertainty-bound non-advisory action candidates.

    Allocation must resolve an action candidate from this store rather than accept a
    caller-supplied JSON artifact. Records are immutable and fingerprinted. Creation
    is intentionally an internal backend concern; no API endpoint exposes ``seal``.
    """

    ARTIFACT_VERSION = "athena-uncertainty-bound-action-candidate-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_uncertainty_bound_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_fingerprint TEXT NOT NULL UNIQUE,
                    decision_id TEXT NOT NULL,
                    decision_fingerprint TEXT NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_uncertainty_bound_actions_instrument_as_of
                ON athena_recommendation_uncertainty_bound_actions(instrument_id, as_of);
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self.validate_artifact(artifact)
        candidate_fingerprint = self._sha256(
            validated.get("uncertaintyBoundActionCandidateFingerprint"),
            "uncertaintyBoundActionCandidateFingerprint",
        )
        decision_id = self._text(
            validated.get("actionPromotionDecisionId"), "actionPromotionDecisionId"
        )
        decision_fingerprint = self._sha256(
            validated.get("actionPromotionDecisionFingerprint"),
            "actionPromotionDecisionFingerprint",
        )
        instrument_id = self._positive_int(validated.get("instrumentId"), "instrumentId")
        as_of = self._aware_iso(validated.get("asOf"), "asOf").isoformat()
        serialized = self._serialize(validated)

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_uncertainty_bound_actions
                WHERE candidate_fingerprint = ?
                """,
                (candidate_fingerprint,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la acción sellada.")
                if record["artifact"] != validated:
                    raise ValueError("La acción ligada a incertidumbre es inmutable.")
                return record

            persisted_at = datetime.now(timezone.utc).isoformat()
            record_core = {
                "candidateFingerprint": candidate_fingerprint,
                "decisionId": decision_id,
                "decisionFingerprint": decision_fingerprint,
                "instrumentId": instrument_id,
                "asOf": as_of,
                "artifact": validated,
                "persistedAt": persisted_at,
            }
            record_fingerprint = self._fingerprint(record_core)
            connection.execute(
                """
                INSERT INTO athena_recommendation_uncertainty_bound_actions (
                    candidate_fingerprint,
                    decision_id,
                    decision_fingerprint,
                    instrument_id,
                    as_of,
                    artifact_json,
                    persisted_at,
                    record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_fingerprint,
                    decision_id,
                    decision_fingerprint,
                    instrument_id,
                    as_of,
                    serialized,
                    persisted_at,
                    record_fingerprint,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_uncertainty_bound_actions
                WHERE candidate_fingerprint = ?
                """,
                (candidate_fingerprint,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la acción sellada.")
        return result

    def get(self, *, candidate_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(candidate_fingerprint, "candidate_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_uncertainty_bound_actions
                WHERE candidate_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de acción debe ser un objeto.")
        candidate_fingerprint = self._sha256(
            record.get("candidate_fingerprint"), "candidate_fingerprint"
        )
        decision_id = self._text(record.get("decision_id"), "decision_id")
        decision_fingerprint = self._sha256(
            record.get("decision_fingerprint"), "decision_fingerprint"
        )
        instrument_id = self._positive_int(record.get("instrument_id"), "instrument_id")
        as_of = self._aware_iso(record.get("as_of"), "as_of").isoformat()
        persisted_at = self._aware_iso(record.get("persisted_at"), "persisted_at").isoformat()
        artifact = self.validate_artifact(record.get("artifact"))
        if artifact.get("uncertaintyBoundActionCandidateFingerprint") != candidate_fingerprint:
            raise ValueError("El registro cambió el fingerprint del candidato.")
        if artifact.get("actionPromotionDecisionId") != decision_id:
            raise ValueError("El registro cambió la decisión de promoción.")
        if artifact.get("actionPromotionDecisionFingerprint") != decision_fingerprint:
            raise ValueError("El registro cambió el fingerprint de decisión.")
        if artifact.get("instrumentId") != instrument_id:
            raise ValueError("El registro cambió instrumentId.")
        if self._aware_iso(artifact.get("asOf"), "artifact.asOf").isoformat() != as_of:
            raise ValueError("El registro cambió as_of.")
        supplied_record_fingerprint = self._sha256(
            record.get("record_fingerprint"), "record_fingerprint"
        )
        core = {
            "candidateFingerprint": candidate_fingerprint,
            "decisionId": decision_id,
            "decisionFingerprint": decision_fingerprint,
            "instrumentId": instrument_id,
            "asOf": as_of,
            "artifact": artifact,
            "persistedAt": persisted_at,
        }
        if self._fingerprint(core) != supplied_record_fingerprint:
            raise ValueError("El registro de acción fue modificado.")
        return record

    def validate_artifact(self, artifact: object) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("El candidato ligado a incertidumbre debe ser un objeto.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de candidato ligado a incertidumbre no soportada.")
        if artifact.get("status") != "uncertainty_bound_action_candidate_non_advisory":
            raise ValueError("El candidato de acción debe permanecer no advisory.")
        if artifact.get("uncertaintyBoundActionEvidenceReady") is not True:
            raise ValueError("La evidencia de acción/incertidumbre no está preparada.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato intentó emitir advice.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "allocationEligible",
            "automaticTrading",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"El candidato violó {field}=False.")
        core_keys = (
            "artifactVersion",
            "validatedActionCandidateFingerprint",
            "actionUncertaintyEvidenceFingerprint",
            "actionPromotionDecisionId",
            "actionPromotionDecisionFingerprint",
            "candidateFingerprint",
            "instrumentId",
            "symbol",
            "asOf",
            "horizonDays",
            "modelFingerprint",
            "policyState",
            "policyFingerprint",
            "portfolioPolicyStateFingerprint",
            "action",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(
            artifact.get("uncertaintyBoundActionCandidateFingerprint"),
            "uncertaintyBoundActionCandidateFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("El candidato ligado a incertidumbre fue modificado.")
        self._positive_int(artifact.get("instrumentId"), "instrumentId")
        self._positive_int(artifact.get("horizonDays"), "horizonDays")
        self._aware_iso(artifact.get("asOf"), "asOf")
        for field in (
            "validatedActionCandidateFingerprint",
            "actionUncertaintyEvidenceFingerprint",
            "actionPromotionDecisionFingerprint",
            "candidateFingerprint",
            "modelFingerprint",
            "policyFingerprint",
            "portfolioPolicyStateFingerprint",
        ):
            self._sha256(artifact.get(field), field)
        action = self._text(artifact.get("action"), "action").lower()
        if action not in {"buy", "hold", "reduce", "sell"}:
            raise ValueError("La acción no está soportada.")
        return artifact

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "candidate_fingerprint": str(row["candidate_fingerprint"]),
            "decision_id": str(row["decision_id"]),
            "decision_fingerprint": str(row["decision_fingerprint"]),
            "instrument_id": int(row["instrument_id"]),
            "as_of": str(row["as_of"]),
            "artifact": artifact,
            "persisted_at": str(row["persisted_at"]),
            "record_fingerprint": str(row["record_fingerprint"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("La acción contiene datos no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _aware_iso(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser fecha ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha ISO válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)
