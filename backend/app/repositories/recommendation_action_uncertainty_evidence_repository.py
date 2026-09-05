from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationActionUncertaintyEvidenceRepository:
    """Append-only authority for action-uncertainty evidence.

    The artifact remains non-advisory. Persistence proves that an action candidate
    later consumed an exact backend-derived uncertainty artifact rather than a
    caller-supplied JSON object with a self-consistent fingerprint.
    """

    ARTIFACT_VERSION = "athena-action-uncertainty-evidence-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_action_uncertainty_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_fingerprint TEXT NOT NULL UNIQUE,
                    selection_fingerprint TEXT NOT NULL,
                    confirmation_fingerprint TEXT NOT NULL,
                    protocol_fingerprint TEXT NOT NULL,
                    confirmation_as_of TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_action_uncertainty_confirmation
                ON athena_recommendation_action_uncertainty_evidence(confirmation_fingerprint);
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self.validate_artifact(artifact)
        evidence_fingerprint = self._sha256(
            validated.get("actionUncertaintyEvidenceFingerprint"),
            "actionUncertaintyEvidenceFingerprint",
        )
        selection_fingerprint = self._sha256(
            validated.get("selectionFingerprint"), "selectionFingerprint"
        )
        confirmation_fingerprint = self._sha256(
            validated.get("confirmationFingerprint"), "confirmationFingerprint"
        )
        protocol_fingerprint = self._sha256(
            validated.get("protocolFingerprint"), "protocolFingerprint"
        )
        confirmation_as_of = self._aware_iso(
            validated.get("confirmationAsOf"), "confirmationAsOf"
        ).isoformat()
        serialized = self._serialize(validated)

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_uncertainty_evidence
                WHERE evidence_fingerprint = ?
                """,
                (evidence_fingerprint,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la evidencia de incertidumbre.")
                if record["artifact"] != validated:
                    raise ValueError("La evidencia de incertidumbre es inmutable.")
                return record

            persisted_at = datetime.now(timezone.utc).isoformat()
            core = {
                "evidenceFingerprint": evidence_fingerprint,
                "selectionFingerprint": selection_fingerprint,
                "confirmationFingerprint": confirmation_fingerprint,
                "protocolFingerprint": protocol_fingerprint,
                "confirmationAsOf": confirmation_as_of,
                "artifact": validated,
                "persistedAt": persisted_at,
            }
            record_fingerprint = self._fingerprint(core)
            connection.execute(
                """
                INSERT INTO athena_recommendation_action_uncertainty_evidence (
                    evidence_fingerprint,
                    selection_fingerprint,
                    confirmation_fingerprint,
                    protocol_fingerprint,
                    confirmation_as_of,
                    artifact_json,
                    persisted_at,
                    record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_fingerprint,
                    selection_fingerprint,
                    confirmation_fingerprint,
                    protocol_fingerprint,
                    confirmation_as_of,
                    serialized,
                    persisted_at,
                    record_fingerprint,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_uncertainty_evidence
                WHERE evidence_fingerprint = ?
                """,
                (evidence_fingerprint,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la evidencia de incertidumbre.")
        return result

    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(evidence_fingerprint, "evidence_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_uncertainty_evidence
                WHERE evidence_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de incertidumbre debe ser un objeto.")
        evidence_fingerprint = self._sha256(
            record.get("evidence_fingerprint"), "evidence_fingerprint"
        )
        selection_fingerprint = self._sha256(
            record.get("selection_fingerprint"), "selection_fingerprint"
        )
        confirmation_fingerprint = self._sha256(
            record.get("confirmation_fingerprint"), "confirmation_fingerprint"
        )
        protocol_fingerprint = self._sha256(
            record.get("protocol_fingerprint"), "protocol_fingerprint"
        )
        confirmation_as_of = self._aware_iso(
            record.get("confirmation_as_of"), "confirmation_as_of"
        ).isoformat()
        persisted_at = self._aware_iso(record.get("persisted_at"), "persisted_at").isoformat()
        artifact = self.validate_artifact(record.get("artifact"))
        expected = {
            "actionUncertaintyEvidenceFingerprint": evidence_fingerprint,
            "selectionFingerprint": selection_fingerprint,
            "confirmationFingerprint": confirmation_fingerprint,
            "protocolFingerprint": protocol_fingerprint,
        }
        for field, value in expected.items():
            if artifact.get(field) != value:
                raise ValueError(f"El registro cambió {field}.")
        if self._aware_iso(artifact.get("confirmationAsOf"), "artifact.confirmationAsOf").isoformat() != confirmation_as_of:
            raise ValueError("El registro cambió confirmationAsOf.")
        supplied = self._sha256(record.get("record_fingerprint"), "record_fingerprint")
        core = {
            "evidenceFingerprint": evidence_fingerprint,
            "selectionFingerprint": selection_fingerprint,
            "confirmationFingerprint": confirmation_fingerprint,
            "protocolFingerprint": protocol_fingerprint,
            "confirmationAsOf": confirmation_as_of,
            "artifact": artifact,
            "persistedAt": persisted_at,
        }
        if self._fingerprint(core) != supplied:
            raise ValueError("El registro de incertidumbre fue modificado.")
        return record

    def validate_artifact(self, artifact: object) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("La evidencia de incertidumbre debe ser un objeto.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de evidencia de incertidumbre no soportada.")
        if artifact.get("status") not in {
            "action_uncertainty_evidence_ready",
            "action_uncertainty_evidence_insufficient",
        }:
            raise ValueError("Estado de incertidumbre no soportado.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La evidencia intentó emitir advice.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "allocationEligible",
            "automaticProductionPromotion",
            "automaticTrading",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"La evidencia violó {field}=False.")
        if artifact.get("action") is not None or artifact.get("allocation") is not None:
            raise ValueError("La evidencia de incertidumbre no puede contener acción o allocation.")
        core_keys = (
            "artifactVersion",
            "protocolId",
            "protocolFingerprint",
            "protocolRegisteredAt",
            "selectionFingerprint",
            "confirmationFingerprint",
            "economicContractFingerprint",
            "selectedAt",
            "confirmationAsOf",
            "symbolScope",
            "requiredHorizons",
            "horizons",
            "allRequiredPoliciesPassUncertainty",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(
            artifact.get("actionUncertaintyEvidenceFingerprint"),
            "actionUncertaintyEvidenceFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La evidencia de incertidumbre fue modificada.")
        for field in (
            "protocolFingerprint",
            "selectionFingerprint",
            "confirmationFingerprint",
            "economicContractFingerprint",
        ):
            self._sha256(artifact.get(field), field)
        self._aware_iso(artifact.get("protocolRegisteredAt"), "protocolRegisteredAt")
        self._aware_iso(artifact.get("selectedAt"), "selectedAt")
        self._aware_iso(artifact.get("confirmationAsOf"), "confirmationAsOf")
        self._assert_finite(artifact)
        return artifact

    def _assert_finite(self, value: object) -> None:
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("La evidencia contiene valores no finitos.")
            return
        if isinstance(value, dict):
            for item in value.values():
                self._assert_finite(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_finite(item)

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "evidence_fingerprint": str(row["evidence_fingerprint"]),
            "selection_fingerprint": str(row["selection_fingerprint"]),
            "confirmation_fingerprint": str(row["confirmation_fingerprint"]),
            "protocol_fingerprint": str(row["protocol_fingerprint"]),
            "confirmation_as_of": str(row["confirmation_as_of"]),
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
            raise ValueError("La evidencia contiene datos no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

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
