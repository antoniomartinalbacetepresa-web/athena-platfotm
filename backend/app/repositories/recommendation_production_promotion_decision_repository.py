from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationProductionPromotionDecisionRepository:
    """Append-only registry of audited promotion-evidence decisions.

    A decision is not advice or trading authorization. It only records that one
    exact sealed OOS assessment, protocol and per-horizon model identity were
    accepted as calibration evidence. Timestamps and fingerprints are generated
    here so callers cannot backdate or rewrite a decision.
    """

    ARTIFACT_VERSION = "athena-production-promotion-decision-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_production_promotion_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL UNIQUE,
                    research_gate_fingerprint TEXT NOT NULL,
                    protocol_id TEXT NOT NULL,
                    protocol_fingerprint TEXT NOT NULL,
                    confirmation_evidence_fingerprint TEXT NOT NULL,
                    evidence_assessment_fingerprint TEXT NOT NULL UNIQUE,
                    decided_at TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    decision_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_production_promotion_decision_gate
                ON athena_recommendation_production_promotion_decisions(
                    research_gate_fingerprint, decided_at
                );
                """
            )

    def register(self, *, decision_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validated_draft(decision_draft)
        decided_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "decidedAt": decided_at}
        decision_fingerprint = self._fingerprint(unsigned)
        decision = {**unsigned, "decisionFingerprint": decision_fingerprint}
        serialized = self._serialize(decision)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_recommendation_production_promotion_decisions WHERE decision_id = ?",
                (core["decisionId"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la decisión existente.")
                if record["decision"] != decision:
                    raise ValueError("decisionId ya está registrado; las decisiones son inmutables.")
                return record
            connection.execute(
                """
                INSERT INTO athena_recommendation_production_promotion_decisions (
                    decision_id, research_gate_fingerprint, protocol_id,
                    protocol_fingerprint, confirmation_evidence_fingerprint,
                    evidence_assessment_fingerprint, decided_at, decision_json,
                    decision_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    core["decisionId"], core["researchGateFingerprint"],
                    core["protocolId"], core["protocolFingerprint"],
                    core["confirmationEvidenceFingerprint"],
                    core["evidenceAssessmentFingerprint"], decided_at, serialized,
                    decision_fingerprint, created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_recommendation_production_promotion_decisions WHERE decision_id = ?",
                (core["decisionId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la decisión registrada.")
        return result

    def get(self, *, decision_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._non_empty(decision_id, "decision_id")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_recommendation_production_promotion_decisions WHERE decision_id = ?",
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de decisión debe ser un objeto.")
        decision = record.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("El registro carece de decision válida.")
        if decision.get("decisionId") != self._non_empty(record.get("decision_id"), "decision_id"):
            raise ValueError("La decisión persistida cambió de decisionId.")
        for api_key, db_key in (
            ("researchGateFingerprint", "research_gate_fingerprint"),
            ("protocolFingerprint", "protocol_fingerprint"),
            ("confirmationEvidenceFingerprint", "confirmation_evidence_fingerprint"),
            ("evidenceAssessmentFingerprint", "evidence_assessment_fingerprint"),
        ):
            expected = self._sha256(record.get(db_key), db_key)
            if decision.get(api_key) != expected:
                raise ValueError(f"La decisión persistida cambió {api_key}.")
        if decision.get("protocolId") != self._non_empty(record.get("protocol_id"), "protocol_id"):
            raise ValueError("La decisión persistida cambió de protocolId.")
        decided_at = self._aware_iso(record.get("decided_at"), "decided_at")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        if created_at < decided_at:
            raise ValueError("created_at no puede preceder a decided_at.")
        if self._aware_iso(decision.get("decidedAt"), "decidedAt") != decided_at:
            raise ValueError("La decisión persistida cambió su fecha.")
        supplied = self._sha256(record.get("decision_fingerprint"), "decision_fingerprint")
        if decision.get("decisionFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide con la decisión.")
        unsigned = dict(decision)
        unsigned.pop("decisionFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("La decisión fue modificada después de persistirse.")
        self._validated_draft({k: v for k, v in decision.items() if k not in {"decidedAt", "decisionFingerprint"}})
        return record

    def _validated_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("decision_draft debe ser un objeto.")
        if {"decidedAt", "decisionFingerprint"}.intersection(payload):
            raise ValueError("decidedAt y decisionFingerprint los genera el registro.")
        if payload.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de decisión de promoción no compatible.")
        horizons = payload.get("requiredHorizons")
        if not isinstance(horizons, list) or not horizons:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        normalized_horizons: list[int] = []
        for value in horizons:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            normalized_horizons.append(value)
        if len(set(normalized_horizons)) != len(normalized_horizons):
            raise ValueError("requiredHorizons no puede contener duplicados.")
        model_map = self._fingerprint_map(payload.get("modelFingerprintsByHorizon"), normalized_horizons, "modelFingerprintsByHorizon")
        selection_map = self._fingerprint_map(payload.get("selectionFingerprintsByHorizon"), normalized_horizons, "selectionFingerprintsByHorizon")
        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "decisionId": self._non_empty(payload.get("decisionId"), "decisionId"),
            "status": "promotion_evidence_accepted_for_calibration",
            "researchGateFingerprint": self._sha256(payload.get("researchGateFingerprint"), "researchGateFingerprint"),
            "protocolId": self._non_empty(payload.get("protocolId"), "protocolId"),
            "protocolFingerprint": self._sha256(payload.get("protocolFingerprint"), "protocolFingerprint"),
            "confirmationEvidenceFingerprint": self._sha256(payload.get("confirmationEvidenceFingerprint"), "confirmationEvidenceFingerprint"),
            "evidenceAssessmentFingerprint": self._sha256(payload.get("evidenceAssessmentFingerprint"), "evidenceAssessmentFingerprint"),
            "requiredHorizons": normalized_horizons,
            "modelFingerprintsByHorizon": model_map,
            "selectionFingerprintsByHorizon": selection_map,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _fingerprint_map(self, value: object, horizons: list[int], field: str) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError(f"{field} debe ser un objeto.")
        expected = {str(item) for item in horizons}
        if set(value) != expected:
            raise ValueError(f"{field} debe cubrir exactamente requiredHorizons.")
        return {key: self._sha256(value[key], f"{field}.{key}") for key in sorted(expected, key=int)}

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            decision = json.loads(str(row["decision_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("decision_json persistido no es válido.") from exc
        record = {"id": int(row["id"]), "decision_id": str(row["decision_id"]), "research_gate_fingerprint": str(row["research_gate_fingerprint"]), "protocol_id": str(row["protocol_id"]), "protocol_fingerprint": str(row["protocol_fingerprint"]), "confirmation_evidence_fingerprint": str(row["confirmation_evidence_fingerprint"]), "evidence_assessment_fingerprint": str(row["evidence_assessment_fingerprint"]), "decided_at": str(row["decided_at"]), "decision": decision, "decision_fingerprint": str(row["decision_fingerprint"]), "created_at": str(row["created_at"])}
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("La decisión contiene valores no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _non_empty(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._non_empty(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
