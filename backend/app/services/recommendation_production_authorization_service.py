from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.repositories.recommendation_action_promotion_decision_repository import (
    RecommendationActionPromotionDecisionRepository,
)
from app.repositories.recommendation_production_authorization_repository import (
    RecommendationProductionAuthorizationRepository,
)
from app.services.recommendation_calibrated_live_candidate_service import (
    RecommendationCalibratedLiveCandidateService,
)
from app.services.recommendation_production_promotion_decision_service import (
    RecommendationProductionPromotionDecisionService,
)


class _ProductionDecisionService(Protocol):
    def load_verified(self, *, decision_id: str) -> dict[str, Any] | None: ...


class _ActionDecisionRepository(Protocol):
    def get(self, *, decision_id: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _AuthorizationRepository(Protocol):
    ARTIFACT_VERSION: str

    def register(self, *, authorization_draft: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationProductionAuthorizationService:
    """Final offline governance boundary for a productive recommendation.

    A productive artifact can only be minted after exact OOS calibration,
    exact promoted action, precommitted uncertainty evidence, exact portfolio
    policy state and explicit human review all agree on the same immutable
    chain. This boundary is deliberately absent from FastAPI write routes and
    never authorizes allocation or automatic trading.
    """

    CALIBRATED_VERSION = "athena-calibrated-live-candidate-v1"
    ACTION_VERSION = "athena-validated-action-candidate-v1"
    UNCERTAINTY_BOUND_VERSION = "athena-uncertainty-bound-action-candidate-v1"

    def __init__(
        self,
        *,
        production_decision_service: _ProductionDecisionService | None = None,
        action_decision_repository: _ActionDecisionRepository | None = None,
        authorization_repository: _AuthorizationRepository | None = None,
        calibrated_candidate_service: RecommendationCalibratedLiveCandidateService
        | None = None,
    ) -> None:
        self._production_decision_service = (
            production_decision_service
            or RecommendationProductionPromotionDecisionService()
        )
        self._action_decision_repository = (
            action_decision_repository
            or RecommendationActionPromotionDecisionRepository()
        )
        self._authorization_repository = (
            authorization_repository
            or RecommendationProductionAuthorizationRepository()
        )
        self._calibrated_candidate_service = (
            calibrated_candidate_service
            or RecommendationCalibratedLiveCandidateService()
        )

    def authorize(
        self,
        *,
        authorization_id: str,
        production_promotion_decision_id: str,
        calibrated_candidate: dict[str, Any],
        validated_action_candidate: dict[str, Any],
        uncertainty_bound_action_candidate: dict[str, Any],
        operator_id: str,
        authorization_reason: str,
        human_review_confirmed: bool,
    ) -> dict[str, Any]:
        if human_review_confirmed is not True:
            raise ValueError("La autorización productiva exige revisión humana explícita.")

        production_decision = self._production_decision_service.load_verified(
            decision_id=self._text(
                production_promotion_decision_id,
                "production_promotion_decision_id",
            )
        )
        if production_decision is None:
            raise ValueError("La decisión OOS de promoción no está registrada.")
        self._require_non_productive_source(production_decision, "decisión OOS")
        if production_decision.get("calibrationEvidenceReady") is not True:
            raise ValueError("La decisión OOS no habilita evidencia de calibración.")

        calibrated = self._calibrated_candidate_service.validate_artifact(
            calibrated_candidate
        )
        if calibrated is not calibrated_candidate:
            raise ValueError("El validador sustituyó el candidato calibrado.")
        self._require_non_productive_source(calibrated, "candidato calibrado")

        production_decision_fp = self._sha256(
            production_decision.get("decisionFingerprint"),
            "productionPromotionDecisionFingerprint",
        )
        if calibrated.get("promotionDecisionId") != production_decision.get(
            "decisionId"
        ):
            raise ValueError("El candidato calibrado pertenece a otra decisión OOS.")
        if self._sha256(
            calibrated.get("promotionDecisionFingerprint"),
            "calibrated.promotionDecisionFingerprint",
        ) != production_decision_fp:
            raise ValueError("El candidato calibrado no coincide con la decisión OOS.")

        action = self._validated_action(validated_action_candidate)
        calibrated_candidate_fp = self._sha256(
            calibrated.get("calibratedCandidateFingerprint"),
            "calibratedCandidateFingerprint",
        )
        if self._sha256(
            action.get("calibratedCandidateFingerprint"),
            "action.calibratedCandidateFingerprint",
        ) != calibrated_candidate_fp:
            raise ValueError("La acción pertenece a otro candidato calibrado.")

        uncertainty_bound = self._validated_uncertainty_bound(
            uncertainty_bound_action_candidate
        )
        validated_action_fp = self._sha256(
            action.get("validatedActionCandidateFingerprint"),
            "validatedActionCandidateFingerprint",
        )
        if self._sha256(
            uncertainty_bound.get("validatedActionCandidateFingerprint"),
            "uncertainty.validatedActionCandidateFingerprint",
        ) != validated_action_fp:
            raise ValueError("La incertidumbre pertenece a otro candidato de acción.")

        action_decision_id = self._text(
            action.get("actionPromotionDecisionId"),
            "actionPromotionDecisionId",
        )
        action_decision_record = self._action_decision_repository.get(
            decision_id=action_decision_id
        )
        if action_decision_record is None:
            raise ValueError("La decisión de promoción de acciones no está registrada.")
        if self._action_decision_repository.validate_record(
            action_decision_record
        ) is not action_decision_record:
            raise ValueError("El repositorio sustituyó la decisión de acciones.")
        action_decision = action_decision_record.get("decision")
        if not isinstance(action_decision, dict):
            raise ValueError("La decisión de acciones persistida no es válida.")
        self._require_non_productive_source(action_decision, "decisión de acciones")
        if action_decision.get("actionPromotionEvidenceAccepted") is not True:
            raise ValueError("La decisión de acciones no acepta evidencia promovida.")
        action_decision_fp = self._sha256(
            action_decision.get("decisionFingerprint"),
            "actionPromotionDecisionFingerprint",
        )
        if action_decision_fp != self._sha256(
            action.get("actionPromotionDecisionFingerprint"),
            "action.actionPromotionDecisionFingerprint",
        ):
            raise ValueError("La acción no coincide con su decisión persistida.")
        if action_decision_fp != self._sha256(
            uncertainty_bound.get("actionPromotionDecisionFingerprint"),
            "uncertainty.actionPromotionDecisionFingerprint",
        ):
            raise ValueError("La incertidumbre no coincide con la decisión de acciones.")

        chain = self._require_same_identity_and_horizon(
            calibrated=calibrated,
            action=action,
            uncertainty_bound=uncertainty_bound,
        )

        horizon = self._positive_int(action.get("horizonDays"), "horizonDays")
        horizon_key = str(horizon)
        calibrated_horizon = calibrated.get("horizons", {}).get(horizon_key)
        if not isinstance(calibrated_horizon, dict):
            raise ValueError("El candidato calibrado carece del horizonte productivo.")
        if calibrated_horizon.get("calibrationEvidenceBound") is not True:
            raise ValueError("El horizonte productivo no está ligado a evidencia OOS.")
        model_fingerprint = self._sha256(
            action.get("modelFingerprint"), "modelFingerprint"
        )
        if model_fingerprint != self._sha256(
            calibrated_horizon.get("modelFingerprint"),
            "calibrated.modelFingerprint",
        ):
            raise ValueError("El modelo productivo no coincide con el calibrado.")
        expected_production_model = production_decision.get(
            "modelFingerprintsByHorizon", {}
        ).get(horizon_key)
        if model_fingerprint != self._sha256(
            expected_production_model,
            "productionDecision.modelFingerprint",
        ):
            raise ValueError("El modelo productivo no fue aceptado por evidencia OOS.")

        draft = {
            "artifactVersion": self._authorization_repository.ARTIFACT_VERSION,
            "authorizationId": self._text(authorization_id, "authorizationId"),
            "status": "production_recommendation_authorized",
            "productionPromotionDecisionId": production_decision.get("decisionId"),
            "productionPromotionDecisionFingerprint": production_decision_fp,
            "calibratedCandidateFingerprint": calibrated_candidate_fp,
            "validatedActionCandidateFingerprint": validated_action_fp,
            "uncertaintyBoundActionCandidateFingerprint": self._sha256(
                uncertainty_bound.get("uncertaintyBoundActionCandidateFingerprint"),
                "uncertaintyBoundActionCandidateFingerprint",
            ),
            "actionPromotionDecisionId": action_decision_id,
            "actionPromotionDecisionFingerprint": action_decision_fp,
            "candidateFingerprint": chain["candidateFingerprint"],
            "portfolioPolicyStateFingerprint": chain[
                "portfolioPolicyStateFingerprint"
            ],
            "economicContractFingerprint": self._sha256(
                uncertainty_bound.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "instrumentId": self._text(action.get("instrumentId"), "instrumentId"),
            "symbol": self._text(action.get("symbol"), "symbol"),
            "asOf": self._text(action.get("asOf"), "asOf"),
            "horizonDays": horizon,
            "expectedExcessReturn": self._finite(
                action.get("expectedExcessReturn"), "expectedExcessReturn"
            ),
            "modelFingerprint": model_fingerprint,
            "policyState": self._text(action.get("policyState"), "policyState"),
            "policyFingerprint": self._sha256(
                action.get("policyFingerprint"), "policyFingerprint"
            ),
            "action": self._action(action.get("action")),
            "operatorId": self._text(operator_id, "operatorId"),
            "authorizationReason": self._text(
                authorization_reason, "authorizationReason"
            ),
            "humanReviewConfirmed": True,
            "authorizationMethod": "offline_local_operator",
            "advisoryStatus": "production_recommendation",
            "recommendationCandidateReady": True,
            "productionEligible": True,
            "allocationEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }
        return self._authorization_repository.register(
            authorization_draft=draft
        )

    def _validated_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(payload, dict)
            or payload.get("artifactVersion") != self.ACTION_VERSION
        ):
            raise ValueError("Versión de candidato de acción no compatible.")
        if payload.get("status") != "validated_action_candidate_non_advisory":
            raise ValueError("Se exige un candidato de acción validado no advisory.")
        if payload.get("actionEvidenceReady") is not True:
            raise ValueError("La acción no tiene evidencia preparada.")
        self._require_non_productive_source(payload, "candidato de acción")
        if payload.get("allocationEligible") is not False:
            raise ValueError("La acción no puede preautorizar allocation.")
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
        self._finite(payload.get("expectedExcessReturn"), "expectedExcessReturn")
        self._sha256(
            payload.get("portfolioPolicyStateFingerprint"),
            "portfolioPolicyStateFingerprint",
        )
        self._action(payload.get("action"))
        return payload

    def _validated_uncertainty_bound(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if (
            not isinstance(payload, dict)
            or payload.get("artifactVersion") != self.UNCERTAINTY_BOUND_VERSION
        ):
            raise ValueError("Versión de acción ligada a incertidumbre no compatible.")
        if payload.get("status") != "uncertainty_bound_action_candidate_non_advisory":
            raise ValueError("Se exige una acción ligada a incertidumbre no advisory.")
        for field in (
            "actionEvidenceReady",
            "actionUncertaintyEvidenceReady",
            "uncertaintyBoundActionEvidenceReady",
        ):
            if payload.get(field) is not True:
                raise ValueError(f"{field} debe estar preparado.")
        self._require_non_productive_source(payload, "acción con incertidumbre")
        if payload.get("allocationEligible") is not False:
            raise ValueError("La incertidumbre no puede preautorizar allocation.")
        core_keys = (
            "artifactVersion",
            "validatedActionCandidateFingerprint",
            "actionUncertaintyEvidenceFingerprint",
            "actionPromotionDecisionId",
            "actionPromotionDecisionFingerprint",
            "economicContractFingerprint",
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
        core = {key: payload.get(key) for key in core_keys}
        supplied = self._sha256(
            payload.get("uncertaintyBoundActionCandidateFingerprint"),
            "uncertaintyBoundActionCandidateFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La acción ligada a incertidumbre fue modificada.")
        self._sha256(
            payload.get("portfolioPolicyStateFingerprint"),
            "portfolioPolicyStateFingerprint",
        )
        self._sha256(
            payload.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )
        self._action(payload.get("action"))
        return payload

    def _require_same_identity_and_horizon(
        self,
        *,
        calibrated: dict[str, Any],
        action: dict[str, Any],
        uncertainty_bound: dict[str, Any],
    ) -> dict[str, str]:
        calibrated_candidate_fp = self._sha256(
            calibrated.get("candidateFingerprint"),
            "calibrated.candidateFingerprint",
        )
        action_candidate_fp = self._sha256(
            action.get("candidateFingerprint"), "action.candidateFingerprint"
        )
        uncertainty_candidate_fp = self._sha256(
            uncertainty_bound.get("candidateFingerprint"),
            "uncertainty.candidateFingerprint",
        )
        if not (
            calibrated_candidate_fp
            == action_candidate_fp
            == uncertainty_candidate_fp
        ):
            raise ValueError("La cadena productiva mezcla candidatos live distintos.")

        action_portfolio_state_fp = self._sha256(
            action.get("portfolioPolicyStateFingerprint"),
            "action.portfolioPolicyStateFingerprint",
        )
        uncertainty_portfolio_state_fp = self._sha256(
            uncertainty_bound.get("portfolioPolicyStateFingerprint"),
            "uncertainty.portfolioPolicyStateFingerprint",
        )
        if action_portfolio_state_fp != uncertainty_portfolio_state_fp:
            raise ValueError("La cadena productiva cambió el estado sellado de cartera.")

        for field in ("instrumentId", "symbol", "asOf"):
            values = {
                str(calibrated.get(field) or "").strip(),
                str(action.get(field) or "").strip(),
                str(uncertainty_bound.get(field) or "").strip(),
            }
            if "" in values or len(values) != 1:
                raise ValueError(f"La cadena productiva no conserva {field}.")

        action_horizon = self._positive_int(action.get("horizonDays"), "horizonDays")
        uncertainty_horizon = self._positive_int(
            uncertainty_bound.get("horizonDays"), "uncertainty.horizonDays"
        )
        if action_horizon != uncertainty_horizon:
            raise ValueError("La cadena productiva cambió de horizonte.")
        for field in ("modelFingerprint", "policyFingerprint"):
            if self._sha256(action.get(field), f"action.{field}") != self._sha256(
                uncertainty_bound.get(field), f"uncertainty.{field}"
            ):
                raise ValueError(f"La cadena productiva cambió {field}.")
        if self._text(action.get("policyState"), "action.policyState") != self._text(
            uncertainty_bound.get("policyState"), "uncertainty.policyState"
        ):
            raise ValueError("La cadena productiva cambió policyState.")
        if self._action(action.get("action")) != self._action(
            uncertainty_bound.get("action")
        ):
            raise ValueError("La incertidumbre cambió la acción.")

        return {
            "candidateFingerprint": calibrated_candidate_fp,
            "portfolioPolicyStateFingerprint": action_portfolio_state_fp,
        }

    def _require_non_productive_source(
        self, payload: dict[str, Any], label: str
    ) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{label} debe conservar advisoryStatus=no_advice.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{label} no puede estar ya habilitado como recomendación.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{label} no puede estar ya habilitado para producción.")
        if payload.get("automaticTrading") is not False:
            raise ValueError(f"{label} debe mantener automaticTrading=False.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico.")
        parsed = float(value)
        if not (-float("inf") < parsed < float("inf")):
            raise ValueError(f"{field} debe ser finito.")
        return parsed

    def _action(self, value: object) -> str:
        action = self._text(value, "action").lower()
        if action not in {"buy", "hold", "reduce", "sell"}:
            raise ValueError("Acción productiva no soportada.")
        return action

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(
            character not in "0123456789abcdef" for character in result
        ):
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
            raise ValueError(
                "El artefacto contiene valores no serializables o no finitos."
            ) from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
