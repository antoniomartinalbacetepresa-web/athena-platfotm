from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_evidence_service import (
    RecommendationShadowActionCalibrationEvidenceService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


class _EvidenceService(Protocol):
    def assess(self, split: dict[str, Any]) -> dict[str, Any]: ...


class _EconomicContractValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionThresholdResearchReadinessService:
    """Gate threshold research behind PIT evidence and an immutable economic contract.

    This is intentionally not a threshold calibrator. It only establishes that a
    validated split has enough out-of-train discrimination to justify subsequent
    shadow threshold research under explicitly precommitted action semantics and
    costs. The future temporal reserve remains untouched.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-research-readiness-v1"

    def __init__(
        self,
        *,
        evidence_service: _EvidenceService | None = None,
        economic_contract_validator: _EconomicContractValidator | None = None,
    ) -> None:
        self._evidence_service = (
            evidence_service or RecommendationShadowActionCalibrationEvidenceService()
        )
        self._economic_contract_validator = (
            economic_contract_validator or RecommendationShadowActionEconomicContractService()
        )

    def assess(
        self,
        *,
        split: dict[str, Any],
        economic_contract: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = self._evidence_service.assess(split)
        validated_contract = self._economic_contract_validator.validate(economic_contract)
        if validated_contract is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")

        self._assert_shadow_evidence(evidence)
        source_split_fingerprint = self._sha256(
            evidence.get("sourceSplitFingerprint"), "sourceSplitFingerprint"
        )
        if source_split_fingerprint != self._sha256(
            split.get("splitFingerprint"), "splitFingerprint"
        ):
            raise ValueError("La evidencia no corresponde al split suministrado.")
        contract_fingerprint = self._sha256(
            economic_contract.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )

        requested = evidence.get("requestedHorizons")
        horizons = evidence.get("horizons")
        if not isinstance(requested, list) or not requested:
            raise ValueError("La evidencia no contiene horizontes solicitados.")
        if not isinstance(horizons, dict):
            raise ValueError("La evidencia no contiene métricas por horizonte.")

        ready_horizons: list[int] = []
        blocked: dict[str, list[str]] = {}
        for raw_horizon in requested:
            if isinstance(raw_horizon, bool) or not isinstance(raw_horizon, int) or raw_horizon <= 0:
                raise ValueError("La evidencia contiene un horizonte inválido.")
            payload = horizons.get(str(raw_horizon))
            if not isinstance(payload, dict):
                raise ValueError("Falta evidencia para un horizonte solicitado.")
            reasons: list[str] = []
            if payload.get("evidenceSufficientForThresholdResearch") is not True:
                reasons.append("insufficient_calibration_evidence")
            if payload.get("validationSupportsSignalDiscrimination") is not True:
                reasons.append("validation_does_not_support_signal_discrimination")
            if reasons:
                blocked[str(raw_horizon)] = reasons
            else:
                ready_horizons.append(raw_horizon)

        all_horizons_ready = len(ready_horizons) == len(requested)
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceSplitFingerprint": source_split_fingerprint,
            "sourceEvidenceFingerprint": self._sha256(
                evidence.get("evidenceFingerprint"), "evidenceFingerprint"
            ),
            "economicContractFingerprint": contract_fingerprint,
            "requestedHorizons": list(requested),
            "thresholdResearchReadyHorizons": ready_horizons,
            "thresholdResearchReadyHorizonCount": len(ready_horizons),
            "allRequestedHorizonsReadyForThresholdResearch": all_horizons_ready,
            "blockedHorizons": blocked,
        }
        return {
            "status": (
                "shadow_action_threshold_research_ready"
                if all_horizons_ready
                else "shadow_action_threshold_research_blocked"
            ),
            **core,
            "readinessFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            # Readiness to perform controlled research is deliberately distinct
            # from an already-calibrated/promotable action policy.
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "purpose": "precalibration_shadow_threshold_research_readiness",
                "economicContractRequired": True,
                "trainOnlyCandidateGenerationRequired": True,
                "validationOnlyCandidateSelectionRequired": True,
                "futureReserveConsumed": False,
                "thresholdFitting": "not_performed",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _assert_shadow_evidence(self, evidence: dict[str, Any]) -> None:
        if not isinstance(evidence, dict):
            raise ValueError("La evidencia de calibración debe ser un objeto.")
        if evidence.get("advisoryStatus") != "no_advice":
            raise ValueError("La evidencia debe permanecer en no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if evidence.get(field) is not False:
                raise ValueError(f"La evidencia intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if evidence.get(field) is not None:
                raise ValueError(f"La evidencia ya contiene {field}.")
        policy = evidence.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("La evidencia no contiene política shadow.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("La evidencia consumió la reserva temporal futura.")
        if policy.get("thresholdFitting") != "not_performed":
            raise ValueError("La evidencia ya ajustó thresholds.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("La evidencia habilitó promoción automática.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("La evidencia habilitó trading automático.")

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
