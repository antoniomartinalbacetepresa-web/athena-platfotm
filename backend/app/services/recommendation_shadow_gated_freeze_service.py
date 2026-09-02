from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)
from app.services.recommendation_shadow_protocol_selection_service import (
    RecommendationShadowProtocolSelectionService,
)


class RecommendationShadowGatedFreezeService:
    """Freeze a shadow candidate only after verifiable research decisions.

    The research gate validates a candidate protocol/family across walk-forward
    folds. The final research-era refit is therefore not the exact model from a
    single fold. The ridge lambda may not be supplied manually: it must come
    from a fingerprinted protocol-selection artifact derived from validation
    selections, and that artifact must identify the exact walk-forward evidence
    that passed the corresponding research-gate horizon.
    """

    BUNDLE_VERSION = "shadow-gated-freeze-v2"

    def __init__(
        self,
        *,
        holdout_service: RecommendationShadowIndependentHoldoutService | None = None,
        protocol_selection_service: RecommendationShadowProtocolSelectionService | None = None,
    ) -> None:
        self._holdout_service = holdout_service or RecommendationShadowIndependentHoldoutService()
        self._protocol_selection_service = (
            protocol_selection_service or RecommendationShadowProtocolSelectionService()
        )

    def freeze(
        self,
        *,
        research_gate: dict[str, Any],
        protocol_selection: dict[str, Any],
        research_cutoff: datetime,
        horizon_days: int,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(research_cutoff, "research_cutoff")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")

        gate_core = self._validated_gate(research_gate)
        horizon_key = str(int(horizon_days))
        horizon = gate_core["horizons"].get(horizon_key)
        if not isinstance(horizon, dict):
            horizon = gate_core["horizons"].get(int(horizon_days))
        if not isinstance(horizon, dict):
            raise ValueError("El horizonte solicitado no está presente en la research gate.")
        if horizon.get("evaluated") is not True or horizon.get("passesResearchGate") is not True:
            raise ValueError("El horizonte solicitado no superó la research gate.")
        reported_horizon = horizon.get("horizonDays")
        if isinstance(reported_horizon, int) and reported_horizon != int(horizon_days):
            raise ValueError("La evidencia del horizonte es inconsistente.")

        validated_selection = self._protocol_selection_service.validate_selection(
            protocol_selection
        )
        selection_horizon = int(validated_selection.get("horizonDays", -1))
        if selection_horizon != int(horizon_days):
            raise ValueError("La protocol selection no corresponde al horizonte solicitado.")

        gate_source_fingerprint = horizon.get("sourceWalkForwardFingerprint")
        selection_source_fingerprint = validated_selection.get(
            "sourceWalkForwardFingerprint"
        )
        if not isinstance(gate_source_fingerprint, str) or not gate_source_fingerprint:
            raise ValueError("La research gate no identifica su evidencia walk-forward fuente.")
        if gate_source_fingerprint != selection_source_fingerprint:
            raise ValueError(
                "La protocol selection no procede del walk-forward que superó la research gate."
            )

        ridge_lambda = float(validated_selection["selectedRidgeLambda"])
        gate_fingerprint = self._fingerprint(gate_core)
        selection_fingerprint = validated_selection.get("selectionFingerprint")
        if not isinstance(selection_fingerprint, str) or not selection_fingerprint:
            raise ValueError("La protocol selection no contiene fingerprint válido.")

        frozen = self._holdout_service.freeze(
            research_cutoff=cutoff,
            horizon_days=int(horizon_days),
            ridge_lambda=ridge_lambda,
        )
        self._assert_shadow(frozen, "frozen_model")
        if frozen.get("status") != "shadow_model_frozen":
            return {
                "status": "shadow_gated_freeze_blocked",
                "reason": frozen.get("status", "freeze_failed"),
                "researchGateFingerprint": gate_fingerprint,
                "protocolSelectionFingerprint": selection_fingerprint,
                "sourceWalkForwardFingerprint": gate_source_fingerprint,
                "horizonDays": int(horizon_days),
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": {
                    "actions": "not_assigned",
                    "automaticProductionPromotion": False,
                },
            }

        if int(frozen.get("horizonDays", -1)) != int(horizon_days):
            raise ValueError("El artefacto congelado cambió de horizonte.")
        if frozen.get("researchCutoff") != cutoff.isoformat():
            raise ValueError("El artefacto congelado cambió el researchCutoff.")
        if float(frozen.get("ridgeLambda", -1.0)) != ridge_lambda:
            raise ValueError("El artefacto congelado cambió la lambda seleccionada.")

        bundle_core = {
            "bundleVersion": self.BUNDLE_VERSION,
            "researchGateFingerprint": gate_fingerprint,
            "protocolSelectionFingerprint": selection_fingerprint,
            "sourceWalkForwardFingerprint": gate_source_fingerprint,
            "researchGateStatus": gate_core["status"],
            "horizonDays": int(horizon_days),
            "researchCutoff": cutoff.isoformat(),
            "ridgeLambda": ridge_lambda,
            "modelFingerprint": frozen["fingerprint"],
            "freezeProtocol": "refit_on_all_mature_research_rows_before_holdout",
            "ridgeSelectionProtocol": (
                "modal_validation_selected_lambda_stronger_regularization_on_tie"
            ),
            "researchIdentity": "candidate_protocol_not_single_walk_forward_fold_model",
        }
        bundle_fingerprint = self._fingerprint(bundle_core)
        return {
            "status": "shadow_research_gated_model_frozen",
            **bundle_core,
            "bundleFingerprint": bundle_fingerprint,
            "frozenModel": frozen,
            "researchGateEvidence": gate_core,
            "protocolSelectionEvidence": validated_selection,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "gatePassRequired": True,
                "passingHorizonRequired": True,
                "sameWalkForwardEvidenceRequired": True,
                "researchDerivedLambdaRequired": True,
                "manualPostResearchLambdaSelection": False,
                "foldTestMetricsMaySelectLambda": False,
                "freezeBeforeHoldout": True,
                "holdoutCanChangeModel": False,
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
            },
        }

    def validate_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if bundle.get("status") != "shadow_research_gated_model_frozen":
            raise ValueError("Se requiere un bundle shadow_research_gated_model_frozen.")
        self._assert_shadow(bundle, "gated_bundle")

        gate_core = self._validated_gate(bundle.get("researchGateEvidence"))
        expected_gate_fingerprint = self._fingerprint(gate_core)
        if expected_gate_fingerprint != bundle.get("researchGateFingerprint"):
            raise ValueError("La evidencia de research gate fue modificada tras la congelación.")

        selection = bundle.get("protocolSelectionEvidence")
        if not isinstance(selection, dict):
            raise ValueError("El bundle no contiene protocolSelectionEvidence válida.")
        validated_selection = self._protocol_selection_service.validate_selection(selection)
        if validated_selection.get("selectionFingerprint") != bundle.get(
            "protocolSelectionFingerprint"
        ):
            raise ValueError("La protocol selection no coincide con el bundle.")

        horizon_key = str(int(bundle.get("horizonDays", -1)))
        gate_horizon = gate_core["horizons"].get(horizon_key)
        if not isinstance(gate_horizon, dict):
            raise ValueError("El horizonte del bundle no existe en la research gate.")
        gate_source_fingerprint = gate_horizon.get("sourceWalkForwardFingerprint")
        selection_source_fingerprint = validated_selection.get(
            "sourceWalkForwardFingerprint"
        )
        if gate_source_fingerprint != selection_source_fingerprint:
            raise ValueError("Gate y protocol selection ya no comparten walk-forward fuente.")
        if gate_source_fingerprint != bundle.get("sourceWalkForwardFingerprint"):
            raise ValueError("El walk-forward fuente no coincide con el bundle.")

        frozen = bundle.get("frozenModel")
        if not isinstance(frozen, dict):
            raise ValueError("El bundle no contiene frozenModel válido.")
        self._assert_shadow(frozen, "frozen_model")
        if frozen.get("fingerprint") != bundle.get("modelFingerprint"):
            raise ValueError("El fingerprint del modelo no coincide con el bundle.")

        core_keys = (
            "bundleVersion",
            "researchGateFingerprint",
            "protocolSelectionFingerprint",
            "sourceWalkForwardFingerprint",
            "researchGateStatus",
            "horizonDays",
            "researchCutoff",
            "ridgeLambda",
            "modelFingerprint",
            "freezeProtocol",
            "ridgeSelectionProtocol",
            "researchIdentity",
        )
        core = {key: bundle.get(key) for key in core_keys}
        if core["bundleVersion"] != self.BUNDLE_VERSION:
            raise ValueError("Versión de gated freeze no compatible.")
        if self._fingerprint(core) != bundle.get("bundleFingerprint"):
            raise ValueError("El bundle gated freeze fue modificado tras su creación.")
        if int(frozen.get("horizonDays", -1)) != int(core["horizonDays"]):
            raise ValueError("El horizonte del modelo no coincide con el bundle.")
        if frozen.get("researchCutoff") != core["researchCutoff"]:
            raise ValueError("El researchCutoff del modelo no coincide con el bundle.")
        if float(frozen.get("ridgeLambda", -1.0)) != float(core["ridgeLambda"]):
            raise ValueError("La lambda del modelo no coincide con el bundle.")
        if int(validated_selection.get("horizonDays", -1)) != int(core["horizonDays"]):
            raise ValueError("El horizonte de protocol selection no coincide con el bundle.")
        if float(validated_selection.get("selectedRidgeLambda", -1.0)) != float(
            core["ridgeLambda"]
        ):
            raise ValueError("La lambda de protocol selection no coincide con el bundle.")
        return bundle

    def _validated_gate(self, gate: object) -> dict[str, Any]:
        if not isinstance(gate, dict):
            raise ValueError("research_gate debe ser un objeto válido.")
        self._assert_shadow(gate, "research_gate")
        if gate.get("researchStageEligible") is not True:
            raise ValueError("La research gate no autoriza avanzar a la siguiente fase.")
        horizons = gate.get("horizons")
        thresholds = gate.get("thresholds")
        if not isinstance(horizons, dict) or not isinstance(thresholds, dict):
            raise ValueError("La research gate debe incluir horizons y thresholds.")
        core = {
            "status": gate.get("status"),
            "evaluatedHorizonCount": gate.get("evaluatedHorizonCount"),
            "passingHorizonCount": gate.get("passingHorizonCount"),
            "horizonPassRatio": gate.get("horizonPassRatio"),
            "researchStageEligible": True,
            "globalReasons": gate.get("globalReasons", []),
            "horizons": horizons,
            "thresholds": thresholds,
            "thresholdStatus": gate.get("thresholdStatus"),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }
        self._fingerprint(core)
        return core

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó el contrato no_advice.")

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
