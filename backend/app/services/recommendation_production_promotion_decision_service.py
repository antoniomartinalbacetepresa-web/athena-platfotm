from __future__ import annotations

import hashlib
import json
from typing import Any

from app.repositories.recommendation_production_promotion_decision_repository import (
    RecommendationProductionPromotionDecisionRepository,
)


class RecommendationProductionPromotionDecisionService:
    """Persist a fail-closed decision from already verified registered OOS evidence.

    This is deliberately one step short of a productive recommendation. A valid
    decision means only that exact sealed evidence for exact per-horizon model and
    selection fingerprints may satisfy the calibration-evidence prerequisite.
    """

    def __init__(
        self,
        repository: RecommendationProductionPromotionDecisionRepository | None = None,
    ) -> None:
        self._repository = repository or RecommendationProductionPromotionDecisionRepository()

    def decide(
        self,
        *,
        decision_id: str,
        promotion_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = self._validated_evidence(promotion_evidence)
        horizons = list(evidence["requiredHorizons"])
        model_map: dict[str, str] = {}
        selection_map: dict[str, str] = {}
        for horizon in horizons:
            key = str(horizon)
            item = evidence["horizons"][key]
            model_map[key] = self._sha256(item.get("modelFingerprint"), f"modelFingerprint.{key}")
            selection_map[key] = self._sha256(item.get("selectionFingerprint"), f"selectionFingerprint.{key}")

        assessment_core = {
            "protocolId": evidence["protocolId"],
            "protocolFingerprint": evidence["protocolFingerprint"],
            "researchGateFingerprint": evidence["researchGateFingerprint"],
            "researchCutoff": evidence["researchCutoff"],
            "confirmationEvidenceFingerprint": evidence["confirmationEvidenceFingerprint"],
            "requiredHorizons": horizons,
            "modelFingerprintsByHorizon": model_map,
            "selectionFingerprintsByHorizon": selection_map,
        }
        assessment_fingerprint = self._fingerprint(assessment_core)
        record = self._repository.register(
            decision_draft={
                "artifactVersion": self._repository.ARTIFACT_VERSION,
                "decisionId": self._non_empty(decision_id, "decision_id"),
                "researchGateFingerprint": evidence["researchGateFingerprint"],
                "protocolId": evidence["protocolId"],
                "protocolFingerprint": evidence["protocolFingerprint"],
                "confirmationEvidenceFingerprint": evidence["confirmationEvidenceFingerprint"],
                "evidenceAssessmentFingerprint": assessment_fingerprint,
                "requiredHorizons": horizons,
                "modelFingerprintsByHorizon": model_map,
                "selectionFingerprintsByHorizon": selection_map,
            }
        )
        decision = record["decision"]
        return {
            **decision,
            "calibrationEvidenceReady": True,
            "decisionPersistence": {
                "registered": True,
                "recordId": record["id"],
                "createdAt": record["created_at"],
                "decidedAt": record["decided_at"],
                "decisionFingerprint": record["decision_fingerprint"],
            },
            "policy": {
                "exactRegisteredProtocolRequired": True,
                "exactSealedConfirmationRequired": True,
                "exactPerHorizonModelIdentityRequired": True,
                "exactPerHorizonSelectionIdentityRequired": True,
                "decisionIsCalibrationEvidenceOnly": True,
                "decisionIsNotAdvice": True,
                "decisionIsNotProductionAuthorization": True,
                "automaticTrading": False,
            },
        }

    def load_verified(self, *, decision_id: str) -> dict[str, Any] | None:
        record = self._repository.get(decision_id=self._non_empty(decision_id, "decision_id"))
        if record is None:
            return None
        validated = self._repository.validate_record(record)
        return {
            **validated["decision"],
            "calibrationEvidenceReady": True,
        }

    def _validated_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("promotion_evidence debe ser un objeto.")
        if payload.get("productionPromotionEvidenceReady") is not True:
            raise ValueError("La evidencia OOS registrada todavía no supera el protocolo.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La evidencia violó advisoryStatus=no_advice.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "automaticProductionPromotion",
            "automaticTrading",
        ):
            if payload.get(field) is not False:
                raise ValueError(f"La evidencia violó {field}=False.")
        persistence = payload.get("protocolPersistence")
        if not isinstance(persistence, dict) or persistence.get("registered") is not True:
            raise ValueError("La ruta productiva exige un protocolo persistido y verificado.")
        protocol_fingerprint = self._sha256(payload.get("protocolFingerprint"), "protocolFingerprint")
        persisted_fingerprint = self._sha256(
            persistence.get("protocolFingerprint"), "protocolPersistence.protocolFingerprint"
        )
        if persisted_fingerprint != protocol_fingerprint:
            raise ValueError("El protocolo evaluado no coincide con el protocolo persistido.")
        self._sha256(payload.get("researchGateFingerprint"), "researchGateFingerprint")
        self._sha256(payload.get("confirmationEvidenceFingerprint"), "confirmationEvidenceFingerprint")
        horizons = payload.get("requiredHorizons")
        if not isinstance(horizons, list) or not horizons:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        normalized: list[int] = []
        for value in horizons:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            normalized.append(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("requiredHorizons no puede contener duplicados.")
        horizon_payload = payload.get("horizons")
        if not isinstance(horizon_payload, dict):
            raise ValueError("La evidencia debe incluir horizons.")
        if set(horizon_payload) != {str(value) for value in normalized}:
            raise ValueError("horizons debe cubrir exactamente requiredHorizons.")
        for horizon in normalized:
            item = horizon_payload[str(horizon)]
            if not isinstance(item, dict) or item.get("passesPrecommittedCriteria") is not True:
                raise ValueError("Todos los horizontes requeridos deben superar criterios precomprometidos.")
            blockers = item.get("blockers")
            if blockers not in ([], tuple()):
                raise ValueError("Un horizonte aprobado no puede conservar blockers.")
            self._sha256(item.get("modelFingerprint"), f"modelFingerprint.{horizon}")
            self._sha256(item.get("selectionFingerprint"), f"selectionFingerprint.{horizon}")
        return {**payload, "requiredHorizons": normalized}

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        try:
            serialized = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("La evidencia contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

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
