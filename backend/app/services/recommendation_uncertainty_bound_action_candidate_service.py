from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.repositories.recommendation_action_promotion_decision_repository import (
    RecommendationActionPromotionDecisionRepository,
)


class _DecisionRepository(Protocol):
    def get(self, *, decision_id: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationUncertaintyBoundActionCandidateService:
    """Bind one validated action to the exact promoted policy's uncertainty gate.

    The service does not decide a new action and cannot size a position. It proves
    that the current non-advisory action candidate, its persisted model/policy
    promotion decision and the precommitted uncertainty evidence all refer to the
    same selection, first-sealed confirmation, horizon and portfolio policy state.
    """

    ARTIFACT_VERSION = "athena-uncertainty-bound-action-candidate-v1"
    ACTION_VERSION = "athena-validated-action-candidate-v1"
    UNCERTAINTY_VERSION = "athena-action-uncertainty-evidence-v1"
    ACTIONS = ("buy", "hold", "reduce", "sell")

    def __init__(
        self,
        *,
        decision_repository: _DecisionRepository | None = None,
    ) -> None:
        self._decision_repository = (
            decision_repository or RecommendationActionPromotionDecisionRepository()
        )

    def build(
        self,
        *,
        validated_action_candidate: dict[str, Any],
        uncertainty_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        action_candidate = self._validated_action(validated_action_candidate)
        uncertainty = self._validated_uncertainty(uncertainty_evidence)

        decision_id = self._text(
            action_candidate.get("actionPromotionDecisionId"),
            "actionPromotionDecisionId",
        )
        record = self._decision_repository.get(decision_id=decision_id)
        if record is None:
            raise ValueError("La decisión de promoción de acciones no está registrada.")
        if self._decision_repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó la decisión de promoción.")
        decision = record.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("La decisión persistida carece de payload válido.")
        if decision.get("actionPromotionEvidenceAccepted") is not True:
            raise ValueError("La decisión persistida no acepta la evidencia de acciones.")
        self._assert_non_productive(decision, "decisión")

        decision_fingerprint = self._sha256(
            decision.get("decisionFingerprint"), "decisionFingerprint"
        )
        if decision_fingerprint != self._sha256(
            action_candidate.get("actionPromotionDecisionFingerprint"),
            "actionPromotionDecisionFingerprint",
        ):
            raise ValueError("El candidato de acción pertenece a otra decisión de promoción.")
        if self._sha256(
            decision.get("selectionFingerprint"), "decision.selectionFingerprint"
        ) != self._sha256(
            uncertainty.get("selectionFingerprint"), "uncertainty.selectionFingerprint"
        ):
            raise ValueError("La incertidumbre pertenece a otra selección congelada.")
        if self._sha256(
            decision.get("confirmationFingerprint"), "decision.confirmationFingerprint"
        ) != self._sha256(
            uncertainty.get("confirmationFingerprint"), "uncertainty.confirmationFingerprint"
        ):
            raise ValueError("La incertidumbre pertenece a otra confirmación futura.")
        if self._sha256(
            decision.get("economicContractFingerprint"),
            "decision.economicContractFingerprint",
        ) != self._sha256(
            uncertainty.get("economicContractFingerprint"),
            "uncertainty.economicContractFingerprint",
        ):
            raise ValueError("La incertidumbre pertenece a otro contrato económico.")

        horizon = self._positive_int(action_candidate.get("horizonDays"), "horizonDays")
        key = str(horizon)
        required = self._horizons(uncertainty.get("requiredHorizons"))
        if horizon not in required:
            raise ValueError("La incertidumbre no cubre el horizonte del candidato de acción.")
        model_fingerprint = self._sha256(
            action_candidate.get("modelFingerprint"), "modelFingerprint"
        )
        expected_model = decision.get("modelFingerprintsByHorizon", {}).get(key)
        if model_fingerprint != self._sha256(expected_model, "decision.modelFingerprint"):
            raise ValueError("El modelo del candidato no coincide con la decisión promovida.")

        state = self._text(action_candidate.get("policyState"), "policyState")
        policy_fingerprint = self._sha256(
            action_candidate.get("policyFingerprint"), "policyFingerprint"
        )
        expected_policy = (
            decision.get("policyFingerprintsByHorizonAndState", {})
            .get(key, {})
            .get(state)
        )
        if policy_fingerprint != self._sha256(
            expected_policy, "decision.policyFingerprint"
        ):
            raise ValueError("La política del candidato no coincide con la decisión promovida.")

        uncertainty_horizon = uncertainty.get("horizons", {}).get(key)
        if not isinstance(uncertainty_horizon, dict):
            raise ValueError("La evidencia de incertidumbre carece del horizonte requerido.")
        uncertainty_state = uncertainty_horizon.get("states", {}).get(state)
        if not isinstance(uncertainty_state, dict):
            raise ValueError("La evidencia de incertidumbre carece del estado requerido.")
        if uncertainty_state.get("passesPrecommittedUncertaintyCriterion") is not True:
            raise ValueError("La política actual no supera su criterio de incertidumbre precomprometido.")
        if policy_fingerprint != self._sha256(
            uncertainty_state.get("selectedPolicyFingerprint"),
            "uncertainty.selectedPolicyFingerprint",
        ):
            raise ValueError("La incertidumbre pertenece a otra política congelada.")

        action = self._text(action_candidate.get("action"), "action").lower()
        if action not in self.ACTIONS:
            raise ValueError("El candidato contiene una acción no soportada.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "validatedActionCandidateFingerprint": self._sha256(
                action_candidate.get("validatedActionCandidateFingerprint"),
                "validatedActionCandidateFingerprint",
            ),
            "actionUncertaintyEvidenceFingerprint": self._sha256(
                uncertainty.get("actionUncertaintyEvidenceFingerprint"),
                "actionUncertaintyEvidenceFingerprint",
            ),
            "actionPromotionDecisionId": decision_id,
            "actionPromotionDecisionFingerprint": decision_fingerprint,
            "candidateFingerprint": self._sha256(
                action_candidate.get("candidateFingerprint"), "candidateFingerprint"
            ),
            "instrumentId": action_candidate.get("instrumentId"),
            "symbol": action_candidate.get("symbol"),
            "asOf": action_candidate.get("asOf"),
            "horizonDays": horizon,
            "modelFingerprint": model_fingerprint,
            "policyState": state,
            "policyFingerprint": policy_fingerprint,
            "portfolioPolicyStateFingerprint": self._sha256(
                action_candidate.get("portfolioPolicyStateFingerprint"),
                "portfolioPolicyStateFingerprint",
            ),
            "action": action,
        }
        return {
            "status": "uncertainty_bound_action_candidate_non_advisory",
            **core,
            "uncertaintyBoundActionCandidateFingerprint": self._fingerprint(core),
            "actionEvidenceReady": True,
            "actionUncertaintyEvidenceReady": True,
            "uncertaintyBoundActionEvidenceReady": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "exactPersistedActionDecisionRequired": True,
                "exactFirstSealedConfirmationRequired": True,
                "exactPromotedModelRequired": True,
                "exactPromotedPolicyRequired": True,
                "exactPortfolioPolicyStatePreserved": True,
                "uncertaintyCriterionMustBePrecommitted": True,
                "passingUncertaintyIsNotAllocationAuthorization": True,
                "automaticTrading": False,
            },
        }

    def _validated_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("artifactVersion") != self.ACTION_VERSION:
            raise ValueError("Versión de candidato de acción no compatible.")
        if payload.get("status") != "validated_action_candidate_non_advisory":
            raise ValueError("Se exige un candidato de acción validado no advisory.")
        if payload.get("actionEvidenceReady") is not True:
            raise ValueError("El candidato de acción no tiene evidencia preparada.")
        self._assert_non_productive(payload, "candidato de acción")
        if payload.get("allocationEligible") is not False:
            raise ValueError("El candidato de acción no puede prehabilitar allocation.")
        core_keys = (
            "artifactVersion",
            "candidateFingerprint",
            "calibratedCandidateFingerprint",
            "actionPromotionDecisionId",
            "actionPromotionDecisionFingerprint",
            "portfolioPolicyStateFingerprint",
            "instrumentId",
            "symbol",
            "asOf",
            "horizonDays",
            "modelFingerprint",
            "policyState",
            "policyFingerprint",
            "expectedExcessReturn",
            "action",
        )
        core = {key: payload.get(key) for key in core_keys}
        supplied = self._sha256(
            payload.get("validatedActionCandidateFingerprint"),
            "validatedActionCandidateFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("El candidato de acción fue modificado.")
        return payload

    def _validated_uncertainty(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("artifactVersion") != self.UNCERTAINTY_VERSION:
            raise ValueError("Versión de evidencia de incertidumbre no compatible.")
        if payload.get("status") != "action_uncertainty_evidence_ready":
            raise ValueError("Se exige evidencia de incertidumbre preparada.")
        if payload.get("actionUncertaintyEvidenceReady") is not True:
            raise ValueError("La evidencia de incertidumbre no está preparada.")
        self._assert_non_productive(payload, "incertidumbre")
        if payload.get("allocationEligible") is not False:
            raise ValueError("La incertidumbre no puede prehabilitar allocation.")
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
        core = {key: payload.get(key) for key in core_keys}
        supplied = self._sha256(
            payload.get("actionUncertaintyEvidenceFingerprint"),
            "actionUncertaintyEvidenceFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La evidencia de incertidumbre fue modificada.")
        return payload

    def _assert_non_productive(self, payload: dict[str, Any], label: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"El artefacto {label} debe mantener no_advice.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"El artefacto {label} no puede habilitar recomendaciones.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"El artefacto {label} no puede habilitar producción.")
        if payload.get("automaticTrading") is not False:
            raise ValueError(f"El artefacto {label} debe mantener automaticTrading=False.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        result = [self._positive_int(item, "requiredHorizons") for item in value]
        if len(set(result)) != len(result):
            raise ValueError("requiredHorizons contiene duplicados.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

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
            raise ValueError("El artefacto contiene valores no finitos/no serializables.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
