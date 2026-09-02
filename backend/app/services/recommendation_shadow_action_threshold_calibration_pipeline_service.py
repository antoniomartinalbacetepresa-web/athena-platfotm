from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)
from app.services.recommendation_shadow_action_calibration_utility_panel_service import (
    RecommendationShadowActionCalibrationUtilityPanelService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_shadow_action_threshold_freeze_service import (
    RecommendationShadowActionThresholdFreezeService,
)
from app.services.recommendation_shadow_action_threshold_research_readiness_service import (
    RecommendationShadowActionThresholdResearchReadinessService,
)


class _SplitService(Protocol):
    def build(
        self,
        *,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int],
    ) -> dict[str, Any]: ...


class _EconomicContractService(Protocol):
    def build(
        self,
        *,
        transaction_cost_bps: float,
        slippage_bps: float,
        reduced_exposure_fraction: float,
        objective_name: str,
        objective_version: str,
    ) -> dict[str, Any]: ...


class _ReadinessService(Protocol):
    def assess(
        self,
        *,
        split: dict[str, Any],
        economic_contract: dict[str, Any],
    ) -> dict[str, Any]: ...


class _UtilityPanelService(Protocol):
    def build(
        self,
        *,
        split: dict[str, Any],
        economic_contract: dict[str, Any],
    ) -> dict[str, Any]: ...


class _FreezeService(Protocol):
    def freeze(self, *, utility_panel: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionThresholdCalibrationPipelineService:
    """Connect trusted live PIT evidence to an immutable shadow-threshold freeze.

    No caller may inject train/validation rows, candidate thresholds or a selection
    timestamp. Rows come from the split service, economic assumptions become a
    fingerprinted contract, readiness gates threshold fitting, and the successful
    validation selection is immediately committed by the freeze service.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-calibration-pipeline-v1"
    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        split_service: _SplitService | None = None,
        economic_contract_service: _EconomicContractService | None = None,
        readiness_service: _ReadinessService | None = None,
        utility_panel_service: _UtilityPanelService | None = None,
        freeze_service: _FreezeService | None = None,
    ) -> None:
        self._split_service = split_service or RecommendationShadowActionCalibrationSplitService()
        self._economic_contract_service = (
            economic_contract_service or RecommendationShadowActionEconomicContractService()
        )
        self._readiness_service = (
            readiness_service or RecommendationShadowActionThresholdResearchReadinessService()
        )
        self._utility_panel_service = (
            utility_panel_service or RecommendationShadowActionCalibrationUtilityPanelService()
        )
        self._freeze_service = freeze_service or RecommendationShadowActionThresholdFreezeService()

    def run(
        self,
        *,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        transaction_cost_bps: float,
        slippage_bps: float,
        reduced_exposure_fraction: float,
        objective_name: str,
        objective_version: str,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        split = self._split_service.build(
            train_end=train_end,
            validation_end=validation_end,
            as_of=as_of,
            symbol=symbol,
            horizons=horizons,
        )
        contract = self._economic_contract_service.build(
            transaction_cost_bps=transaction_cost_bps,
            slippage_bps=slippage_bps,
            reduced_exposure_fraction=reduced_exposure_fraction,
            objective_name=objective_name,
            objective_version=objective_version,
        )
        readiness = self._readiness_service.assess(
            split=split,
            economic_contract=contract,
        )
        self._assert_readiness(split=split, contract=contract, readiness=readiness)

        if readiness.get("allRequestedHorizonsReadyForThresholdResearch") is not True:
            return self._blocked_result(split=split, contract=contract, readiness=readiness)

        panel = self._utility_panel_service.build(
            split=split,
            economic_contract=contract,
        )
        self._assert_panel(split=split, contract=contract, panel=panel)
        freeze = self._freeze_service.freeze(utility_panel=panel)
        self._assert_freeze(panel=panel, freeze=freeze)

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceSplitFingerprint": self._sha256(
                split.get("splitFingerprint"), "splitFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                contract.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "readinessFingerprint": self._sha256(
                readiness.get("readinessFingerprint"), "readinessFingerprint"
            ),
            "utilityPanelFingerprint": self._sha256(
                panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
            ),
            "selectionFingerprint": self._sha256(
                freeze.get("selectionFingerprint"), "selectionFingerprint"
            ),
            "freezeFingerprint": self._sha256(
                freeze.get("freezeFingerprint"), "freezeFingerprint"
            ),
            "selectedAt": freeze.get("selectedAt"),
            "requestedHorizons": list(readiness.get("requestedHorizons") or []),
        }
        return {
            "status": "shadow_action_threshold_calibration_frozen_for_future_confirmation",
            **core,
            "pipelineFingerprint": self._fingerprint(core),
            "futureReserveConfirmationEligible": True,
            "economicContract": contract,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": self._policy(frozen=True),
        }

    def _blocked_result(
        self,
        *,
        split: dict[str, Any],
        contract: dict[str, Any],
        readiness: dict[str, Any],
    ) -> dict[str, Any]:
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceSplitFingerprint": self._sha256(
                split.get("splitFingerprint"), "splitFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                contract.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "readinessFingerprint": self._sha256(
                readiness.get("readinessFingerprint"), "readinessFingerprint"
            ),
            "requestedHorizons": list(readiness.get("requestedHorizons") or []),
            "blockedHorizons": readiness.get("blockedHorizons"),
        }
        return {
            "status": "shadow_action_threshold_calibration_blocked_by_evidence",
            **core,
            "pipelineFingerprint": self._fingerprint(core),
            "futureReserveConfirmationEligible": False,
            "economicContract": contract,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": self._policy(frozen=False),
        }

    def _assert_readiness(
        self,
        *,
        split: dict[str, Any],
        contract: dict[str, Any],
        readiness: dict[str, Any],
    ) -> None:
        if not isinstance(readiness, dict):
            raise ValueError("El readiness debe ser un objeto.")
        if readiness.get("sourceSplitFingerprint") != split.get("splitFingerprint"):
            raise ValueError("El readiness no pertenece al split producido.")
        if readiness.get("economicContractFingerprint") != contract.get(
            "economicContractFingerprint"
        ):
            raise ValueError("El readiness no pertenece al contrato producido.")
        self._assert_common_shadow(readiness, "readiness")
        policy = readiness.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El readiness carece de policy.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("El readiness consumió la reserva futura.")
        if policy.get("thresholdFitting") != "not_performed":
            raise ValueError("El readiness ajustó thresholds antes de tiempo.")

    def _assert_panel(
        self,
        *,
        split: dict[str, Any],
        contract: dict[str, Any],
        panel: dict[str, Any],
    ) -> None:
        if not isinstance(panel, dict):
            raise ValueError("El panel de utilidad debe ser un objeto.")
        if panel.get("sourceSplitFingerprint") != split.get("splitFingerprint"):
            raise ValueError("El panel no pertenece al split producido.")
        if panel.get("economicContractFingerprint") != contract.get(
            "economicContractFingerprint"
        ):
            raise ValueError("El panel no pertenece al contrato producido.")
        self._assert_common_shadow(panel, "panel")
        policy = panel.get("policy")
        if not isinstance(policy, dict) or policy.get("futureReserveConsumed") is not False:
            raise ValueError("El panel consumió la reserva futura.")

    def _assert_freeze(
        self,
        *,
        panel: dict[str, Any],
        freeze: dict[str, Any],
    ) -> None:
        if not isinstance(freeze, dict):
            raise ValueError("El freeze debe ser un objeto.")
        panel_fingerprint = self._sha256(
            panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
        )
        freeze_panel_fingerprint = self._sha256(
            freeze.get("sourceUtilityPanelFingerprint"),
            "sourceUtilityPanelFingerprint",
        )
        if freeze_panel_fingerprint != panel_fingerprint:
            raise ValueError("El freeze de thresholds no pertenece al panel de utilidad suministrado.")
        if freeze.get("status") != "shadow_action_thresholds_frozen_before_future_confirmation":
            raise ValueError("La selección no pudo congelarse para confirmación futura.")
        if freeze.get("registered") is not True:
            raise ValueError("La selección no quedó persistida.")
        if freeze.get("futureReserveConfirmationEligible") is not True:
            raise ValueError("El freeze no habilitó confirmación futura.")
        self._assert_common_shadow(freeze, "freeze")
        policy = freeze.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El freeze carece de policy.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("El freeze consumió la reserva futura.")
        if policy.get("callerSuppliedSelectionTimestampAccepted") is not False:
            raise ValueError("El freeze aceptó una frontera temporal del caller.")
        if not panel.get("validationUtilityRows"):
            raise ValueError("El panel congelado carece de validation.")

    def _assert_common_shadow(self, artifact: dict[str, Any], name: str) -> None:
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{name} abandonó no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"{name} intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if artifact.get(field) is not None:
                raise ValueError(f"{name} no puede publicar {field}.")

    def _policy(self, *, frozen: bool) -> dict[str, Any]:
        return {
            "rows": "internally_built_from_trusted_persisted_live_pit_evidence",
            "candidateThresholdGeneration": "train_signal_only",
            "thresholdSelection": "validation_only",
            "selectionTimestamp": (
                "service_clock_immutable_sqlite_boundary" if frozen else "not_created"
            ),
            "freezeBoundToUtilityPanelFingerprint": frozen,
            "futureReserveConsumed": False,
            "futureReserveMayRefitThresholds": False,
            "futureReserveMayReselectPolicies": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
