from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationActionPromotionDecisionRepository:
    """Append-only store for accepted, model-bound action promotion evidence."""

    ARTIFACT_VERSION = "athena-action-promotion-decision-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_action_promotion_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL UNIQUE,
                    model_bound_evidence_fingerprint TEXT NOT NULL UNIQUE,
                    decided_at TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    decision_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_action_promotion_decisions_decided
                ON athena_recommendation_action_promotion_decisions(decided_at);
                """
            )

    def append(
        self,
        *,
        decision_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        normalized_id = self._non_empty(decision_id, "decision_id")
        core = self._validated_evidence_core(evidence)
        decided_at = datetime.now(timezone.utc).isoformat()
        unsigned = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "decisionId": normalized_id,
            **core,
            "decidedAt": decided_at,
        }
        decision_fingerprint = self._fingerprint(unsigned)
        decision = {**unsigned, "decisionFingerprint": decision_fingerprint}
        serialized = self._serialize(decision)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_decisions
                WHERE decision_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la decisión existente.")
                if record["decision"] != decision:
                    raise ValueError("decisionId ya existe; las decisiones son inmutables.")
                return record

            duplicate = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_decisions
                WHERE model_bound_evidence_fingerprint = ?
                """,
                (core["modelBoundActionPromotionEvidenceFingerprint"],),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("La misma evidencia de promoción ya fue decidida.")

            connection.execute(
                """
                INSERT INTO athena_recommendation_action_promotion_decisions (
                    decision_id, model_bound_evidence_fingerprint, decided_at,
                    decision_json, decision_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    core["modelBoundActionPromotionEvidenceFingerprint"],
                    decided_at,
                    serialized,
                    decision_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_decisions
                WHERE decision_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la decisión persistida.")
        return result

    def get(self, *, decision_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._non_empty(decision_id, "decision_id")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_decisions
                WHERE decision_id = ?
                """,
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de decisión debe ser un objeto.")
        decision_id = self._non_empty(record.get("decision_id"), "decision_id")
        evidence_fingerprint = self._sha256(
            record.get("model_bound_evidence_fingerprint"),
            "model_bound_evidence_fingerprint",
        )
        decided_at = self._aware_iso(record.get("decided_at"), "decided_at")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        if created_at < decided_at:
            raise ValueError("created_at no puede preceder a decided_at.")
        decision = record.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("El registro carece de decision válida.")
        if decision.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de decisión no compatible.")
        if decision.get("decisionId") != decision_id:
            raise ValueError("La decisión persistida cambió de decisionId.")
        if decision.get("modelBoundActionPromotionEvidenceFingerprint") != evidence_fingerprint:
            raise ValueError("La decisión cambió de evidencia fuente.")
        if self._aware_iso(decision.get("decidedAt"), "decidedAt") != decided_at:
            raise ValueError("La decisión persistida cambió decidedAt.")
        supplied = self._sha256(record.get("decision_fingerprint"), "decision_fingerprint")
        if decision.get("decisionFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide con la decisión.")
        unsigned = dict(decision)
        unsigned.pop("decisionFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("La decisión fue modificada después de persistirse.")
        self._validated_decision_payload(decision)
        return record

    def _validated_evidence_core(self, evidence: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(evidence, dict):
            raise ValueError("model_bound_evidence debe ser un objeto.")
        if evidence.get("status") != "model_bound_action_promotion_evidence_ready":
            raise ValueError("Sólo puede persistirse evidencia model-bound preparada.")
        if evidence.get("modelBoundActionPromotionEvidenceReady") is not True:
            raise ValueError("La evidencia model-bound no está preparada.")
        self._assert_shadow(evidence)
        horizons = self._horizons(evidence.get("requiredHorizons"))
        models = self._fingerprint_map(
            evidence.get("modelFingerprintsByHorizon"), horizons, "model"
        )
        policies = self._policy_map(
            evidence.get("policyFingerprintsByHorizonAndState"), horizons
        )
        return {
            "modelBoundActionPromotionEvidenceFingerprint": self._sha256(
                evidence.get("modelBoundActionPromotionEvidenceFingerprint"),
                "modelBoundActionPromotionEvidenceFingerprint",
            ),
            "actionPromotionEvidenceFingerprint": self._sha256(
                evidence.get("actionPromotionEvidenceFingerprint"),
                "actionPromotionEvidenceFingerprint",
            ),
            "modelIdentityAttestationFingerprint": self._sha256(
                evidence.get("modelIdentityAttestationFingerprint"),
                "modelIdentityAttestationFingerprint",
            ),
            "protocolId": self._non_empty(evidence.get("protocolId"), "protocolId"),
            "protocolFingerprint": self._sha256(
                evidence.get("protocolFingerprint"), "protocolFingerprint"
            ),
            "selectionFingerprint": self._sha256(
                evidence.get("selectionFingerprint"), "selectionFingerprint"
            ),
            "confirmationFingerprint": self._sha256(
                evidence.get("confirmationFingerprint"), "confirmationFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                evidence.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "requiredHorizons": horizons,
            "modelFingerprintsByHorizon": models,
            "policyFingerprintsByHorizonAndState": policies,
            "actionPromotionEvidenceAccepted": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _validated_decision_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("actionPromotionEvidenceAccepted") is not True:
            raise ValueError("La decisión no acepta explícitamente la evidencia.")
        self._assert_shadow(payload)
        horizons = self._horizons(payload.get("requiredHorizons"))
        self._fingerprint_map(payload.get("modelFingerprintsByHorizon"), horizons, "model")
        self._policy_map(payload.get("policyFingerprintsByHorizonAndState"), horizons)
        for field in (
            "modelBoundActionPromotionEvidenceFingerprint",
            "actionPromotionEvidenceFingerprint",
            "modelIdentityAttestationFingerprint",
            "protocolFingerprint",
            "selectionFingerprint",
            "confirmationFingerprint",
            "economicContractFingerprint",
        ):
            self._sha256(payload.get(field), field)
        self._non_empty(payload.get("protocolId"), "protocolId")

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La decisión debe mantener advisoryStatus=no_advice.")
        for field in ("recommendationCandidateReady", "productionEligible"):
            if payload.get(field) is not False:
                raise ValueError(f"La decisión debe mantener {field}=False.")
        if payload.get("automaticProductionPromotion") is not False:
            raise ValueError("automaticProductionPromotion debe permanecer false.")
        if payload.get("automaticTrading") is not False:
            raise ValueError("automaticTrading debe permanecer false.")
        for field in ("action", "score", "conviction", "allocation"):
            if field in payload and payload.get(field) is not None:
                raise ValueError(f"La decisión no puede publicar {field}.")

    def _policy_map(self, value: object, horizons: list[int]) -> dict[str, dict[str, str]]:
        if not isinstance(value, dict) or set(value) != {str(x) for x in horizons}:
            raise ValueError("El mapa de políticas no cubre exactamente los horizontes.")
        states = ("flat", "reduced_long", "full_long")
        result: dict[str, dict[str, str]] = {}
        for horizon in horizons:
            raw = value.get(str(horizon))
            if not isinstance(raw, dict) or set(raw) != set(states):
                raise ValueError("El mapa de políticas no cubre exactamente todos los estados.")
            result[str(horizon)] = {
                state: self._sha256(raw.get(state), f"policy.{horizon}.{state}")
                for state in states
            }
        return result

    def _fingerprint_map(
        self, value: object, horizons: list[int], field: str
    ) -> dict[str, str]:
        if not isinstance(value, dict) or set(value) != {str(x) for x in horizons}:
            raise ValueError(f"{field}FingerprintsByHorizon no cubre los horizontes.")
        return {
            str(horizon): self._sha256(value.get(str(horizon)), f"{field}.{horizon}")
            for horizon in horizons
        }

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        result: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            result.append(item)
        if len(set(result)) != len(result):
            raise ValueError("requiredHorizons no admite duplicados.")
        return result

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            decision = json.loads(str(row["decision_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("decision_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "decision_id": str(row["decision_id"]),
            "model_bound_evidence_fingerprint": str(
                row["model_bound_evidence_fingerprint"]
            ),
            "decided_at": str(row["decided_at"]),
            "decision": decision,
            "decision_fingerprint": str(row["decision_fingerprint"]),
            "created_at": str(row["created_at"]),
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
            raise ValueError("La decisión contiene valores no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _non_empty(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._non_empty(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
