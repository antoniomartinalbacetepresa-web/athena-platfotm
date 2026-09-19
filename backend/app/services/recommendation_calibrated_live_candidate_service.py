from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.recommendation_production_promotion_decision_service import (
    RecommendationProductionPromotionDecisionService,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class RecommendationCalibratedLiveCandidateService:
    """Bind one live PIT candidate to exact persisted OOS calibration evidence.

    This service intentionally does not assign actions, scores, conviction or
    production eligibility. It proves only that the live candidate uses the same
    research gate, confirmation evidence and frozen per-horizon models that were
    accepted by an immutable calibration-evidence decision.
    """

    ARTIFACT_VERSION = "athena-calibrated-live-candidate-v1"

    def __init__(
        self,
        *,
        live_candidate_service: RecommendationShadowLiveCandidateService | None = None,
        decision_service: RecommendationProductionPromotionDecisionService | None = None,
    ) -> None:
        self._live_candidate_service = live_candidate_service or RecommendationShadowLiveCandidateService()
        self._decision_service = decision_service or RecommendationProductionPromotionDecisionService()

    def bind(
        self,
        *,
        live_candidate: dict[str, Any],
        promotion_decision_id: str,
    ) -> dict[str, Any]:
        candidate = self._live_candidate_service.validate_artifact(live_candidate)
        decision = self._decision_service.load_verified(decision_id=promotion_decision_id)
        if decision is None:
            raise ValueError("La decisión de calibración no está registrada.")
        self._assert_non_productive(candidate, "live_candidate")
        self._assert_non_productive(decision, "promotion_decision")
        if decision.get("calibrationEvidenceReady") is not True:
            raise ValueError("La decisión no habilita evidencia de calibración.")

        if candidate.get("researchGateFingerprint") != decision.get("researchGateFingerprint"):
            raise ValueError("El candidato live pertenece a otra research gate.")
        if candidate.get("confirmationEvidenceFingerprint") != decision.get("confirmationEvidenceFingerprint"):
            raise ValueError("El candidato live pertenece a otra evidencia de confirmación.")

        expected_models = decision.get("modelFingerprintsByHorizon")
        if not isinstance(expected_models, dict) or not expected_models:
            raise ValueError("La decisión carece del mapa de modelos calibrados.")
        horizons = candidate.get("horizons")
        if not isinstance(horizons, dict):
            raise ValueError("El candidato live carece de horizons.")

        bound_horizons: dict[str, dict[str, Any]] = {}
        inferred = 0
        for key, payload in horizons.items():
            if not isinstance(payload, dict):
                raise ValueError("Un horizonte live tiene formato inválido.")
            expected = payload.get("expectedExcessReturn")
            if expected is None:
                bound_horizons[str(key)] = {
                    "horizonDays": payload.get("horizonDays"),
                    "calibrationEvidenceBound": False,
                    "reason": "no_live_inference",
                    "modelFingerprint": payload.get("modelFingerprint"),
                }
                continue
            inferred += 1
            model_fingerprint = self._sha256(payload.get("modelFingerprint"), f"modelFingerprint.{key}")
            calibrated_fingerprint = expected_models.get(str(key))
            if calibrated_fingerprint is None:
                raise ValueError("El candidato infiere un horizonte no incluido en la decisión OOS.")
            if model_fingerprint != self._sha256(calibrated_fingerprint, f"calibratedModelFingerprint.{key}"):
                raise ValueError("El modelo live no coincide con el modelo aceptado por evidencia OOS.")
            bound_horizons[str(key)] = {
                "horizonDays": payload.get("horizonDays"),
                "calibrationEvidenceBound": True,
                "reason": None,
                "modelFingerprint": model_fingerprint,
            }

        if inferred <= 0:
            raise ValueError("No existe ninguna inferencia live que pueda ligarse a calibración.")
        if not all(
            item["calibrationEvidenceBound"]
            for item in bound_horizons.values()
            if item["reason"] != "no_live_inference"
        ):
            raise ValueError("No todas las inferencias live quedaron ligadas a calibración.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "candidateFingerprint": self._sha256(candidate.get("candidateFingerprint"), "candidateFingerprint"),
            "symbol": candidate.get("symbol"),
            "asOf": candidate.get("asOf"),
            "instrumentId": candidate.get("instrumentId"),
            "researchGateFingerprint": decision["researchGateFingerprint"],
            "confirmationEvidenceFingerprint": decision["confirmationEvidenceFingerprint"],
            "promotionDecisionId": decision["decisionId"],
            "promotionDecisionFingerprint": self._sha256(decision.get("decisionFingerprint"), "decisionFingerprint"),
            "protocolId": decision["protocolId"],
            "protocolFingerprint": decision["protocolFingerprint"],
            "horizons": bound_horizons,
        }
        return {
            "status": "live_candidate_bound_to_oos_calibration_evidence",
            **core,
            "calibratedCandidateFingerprint": self._fingerprint(core),
            "calibrationReady": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "calibrationMeaning": "exact_model_identity_bound_to_precommitted_oos_evidence",
                "sameResearchGateRequired": True,
                "sameConfirmationEvidenceRequired": True,
                "samePerHorizonModelRequired": True,
                "calibrationIsNotActionCalibration": True,
                "calibrationIsNotProductionAuthorization": True,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de candidato calibrado no compatible.")
        self._assert_non_productive(artifact, "calibrated_candidate")
        if artifact.get("calibrationReady") is not True:
            raise ValueError("El artefacto no declara calibración ligada.")
        if artifact.get("action") is not None or artifact.get("score") is not None or artifact.get("conviction") is not None:
            raise ValueError("La calibración no puede introducir acción, score ni convicción.")
        supplied = self._sha256(artifact.get("calibratedCandidateFingerprint"), "calibratedCandidateFingerprint")
        keys = (
            "artifactVersion", "candidateFingerprint", "symbol", "asOf", "instrumentId",
            "researchGateFingerprint", "confirmationEvidenceFingerprint", "promotionDecisionId",
            "promotionDecisionFingerprint", "protocolId", "protocolFingerprint", "horizons",
        )
        core = {key: artifact.get(key) for key in keys}
        if self._fingerprint(core) != supplied:
            raise ValueError("El candidato calibrado fue modificado tras su creación.")
        return artifact

    def _assert_non_productive(self, payload: dict[str, Any], field: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{field} debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{field} debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{field} no puede habilitar recomendaciones.")
        if payload.get("automaticTrading") is not False and field != "live_candidate":
            raise ValueError(f"{field} debe mantener automaticTrading=False.")

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("El artefacto contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
