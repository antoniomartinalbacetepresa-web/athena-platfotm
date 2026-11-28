from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.recommendation_action_model_identity_attestation_service import (
    RecommendationActionModelIdentityAttestationService,
)
from app.services.recommendation_action_promotion_evidence_service import (
    RecommendationActionPromotionEvidenceService,
)


class RecommendationModelBoundActionPromotionEvidenceService:
    """Join precommitted action evidence to exact model and policy identity.

    This is the production-path evidence boundary for action policies. It remains
    non-advisory and cannot publish or execute an action. A later decision layer
    may persist the accepted evidence, but only after model and policy binding succeeds.
    """

    ARTIFACT_VERSION = "athena-model-bound-action-promotion-evidence-v2"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(
        self,
        *,
        evidence_service: RecommendationActionPromotionEvidenceService | None = None,
        identity_service: RecommendationActionModelIdentityAttestationService | None = None,
    ) -> None:
        self._evidence_service = evidence_service or RecommendationActionPromotionEvidenceService()
        self._identity_service = identity_service or RecommendationActionModelIdentityAttestationService()

    def evaluate_registered(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
        model_identity_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = self._evidence_service.evaluate_registered(
            confirmation_artifact=confirmation_artifact,
            protocol_id=protocol_id,
        )
        identity = self._identity_service.validate_artifact(model_identity_attestation)
        if identity is not model_identity_attestation:
            raise ValueError("El validador sustituyó la atestación de identidad.")
        self._assert_non_productive(evidence, "action_evidence")
        self._assert_non_productive(identity, "model_identity")

        if evidence.get("selectionFingerprint") != identity.get("selectionFingerprint"):
            raise ValueError("La evidencia y la atestación pertenecen a selecciones distintas.")
        if evidence.get("requiredHorizons") != identity.get("requestedHorizons"):
            raise ValueError("La evidencia y la atestación cubren horizontes distintos.")
        confirmation_contract = self._sha256(
            confirmation_artifact.get("economicContractFingerprint"),
            "confirmation.economicContractFingerprint",
        )
        if confirmation_contract != self._sha256(
            identity.get("economicContractFingerprint"),
            "identity.economicContractFingerprint",
        ):
            raise ValueError("La atestación pertenece a otro contrato económico.")

        models = identity.get("modelFingerprintsByHorizon")
        if not isinstance(models, dict) or not models:
            raise ValueError("La atestación carece de modelos por horizonte.")
        normalized_models = {
            str(key): self._sha256(value, f"modelFingerprintsByHorizon.{key}")
            for key, value in models.items()
        }
        required = [int(value) for value in evidence.get("requiredHorizons") or []]
        if set(normalized_models) != {str(value) for value in required}:
            raise ValueError("La identidad de modelo no cubre exactamente los horizontes promovidos.")

        evidence_horizons = evidence.get("horizons")
        if not isinstance(evidence_horizons, dict):
            raise ValueError("La evidencia de acción carece de horizontes.")
        policy_map: dict[str, dict[str, str]] = {}
        for horizon in required:
            key = str(horizon)
            horizon_payload = evidence_horizons.get(key)
            if not isinstance(horizon_payload, dict):
                raise ValueError("Falta la evidencia de un horizonte promovido.")
            states = horizon_payload.get("states")
            if not isinstance(states, dict) or set(states) != set(self.STATES):
                raise ValueError("La evidencia de acción no cubre exactamente todos los estados.")
            policy_map[key] = {
                state: self._sha256(
                    states[state].get("selectedPolicyFingerprint")
                    if isinstance(states[state], dict)
                    else None,
                    f"selectedPolicyFingerprint.{key}.{state}",
                )
                for state in self.STATES
            }

        ready = evidence.get("actionPromotionEvidenceReady") is True
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "actionPromotionEvidenceFingerprint": self._sha256(
                evidence.get("actionPromotionEvidenceFingerprint"),
                "actionPromotionEvidenceFingerprint",
            ),
            "modelIdentityAttestationFingerprint": self._sha256(
                identity.get("modelIdentityAttestationFingerprint"),
                "modelIdentityAttestationFingerprint",
            ),
            "protocolId": evidence.get("protocolId"),
            "protocolFingerprint": self._sha256(
                evidence.get("protocolFingerprint"), "protocolFingerprint"
            ),
            "selectionFingerprint": self._sha256(
                evidence.get("selectionFingerprint"), "selectionFingerprint"
            ),
            "confirmationFingerprint": self._sha256(
                evidence.get("confirmationFingerprint"), "confirmationFingerprint"
            ),
            "economicContractFingerprint": confirmation_contract,
            "requiredHorizons": required,
            "modelFingerprintsByHorizon": normalized_models,
            "policyFingerprintsByHorizonAndState": policy_map,
            "actionPromotionEvidenceReady": ready,
        }
        return {
            "status": (
                "model_bound_action_promotion_evidence_ready"
                if ready
                else "model_bound_action_promotion_evidence_insufficient"
            ),
            **core,
            "modelBoundActionPromotionEvidenceFingerprint": self._fingerprint(core),
            "modelBoundActionPromotionEvidenceReady": ready,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "allocation": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "precommittedActionProtocolRequired": True,
                "firstSealedFutureReserveRequired": True,
                "singleModelRevisionPerHorizonRequired": True,
                "exactModelIdentityMustMatchFutureLiveCandidate": True,
                "exactPolicyIdentityBoundPerHorizonAndState": True,
                "portfolioStateStillRequiredForReduceOrSell": True,
                "evidenceReadyIsNotProductionAuthorization": True,
                "automaticTrading": False,
            },
        }

    def _assert_non_productive(self, payload: dict[str, Any], field: str) -> None:
        if not isinstance(payload, dict):
            raise ValueError(f"{field} debe ser un objeto.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{field} debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{field} debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{field} no puede habilitar recomendaciones.")
        if payload.get("action") is not None:
            raise ValueError(f"{field} no puede contener action.")
        if payload.get("automaticTrading") is not False:
            raise ValueError(f"{field} debe mantener automaticTrading=False.")

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        try:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El artefacto contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
