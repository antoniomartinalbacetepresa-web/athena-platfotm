from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
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
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
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


class RecommendationShadowActionThresholdResearchPipelineService:
    """Connect live PIT rows to threshold-research readiness without fitting actions.

    Split rows are produced internally from persisted live evidence. Economic
    assumptions are explicit caller inputs and become part of the immutable
    contract fingerprint; no train/validation rows or thresholds can be injected.
    """

    def __init__(
        self,
        *,
        split_service: _SplitService | None = None,
        economic_contract_service: _EconomicContractService | None = None,
        readiness_service: _ReadinessService | None = None,
    ) -> None:
        self._split_service = split_service or RecommendationShadowActionCalibrationSplitService()
        self._economic_contract_service = (
            economic_contract_service or RecommendationShadowActionEconomicContractService()
        )
        self._readiness_service = (
            readiness_service or RecommendationShadowActionThresholdResearchReadinessService()
        )

    def evaluate(
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
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
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
        result = self._readiness_service.assess(
            split=split,
            economic_contract=contract,
        )
        self._assert_output(split=split, contract=contract, result=result)
        return result

    def _assert_output(
        self,
        *,
        split: dict[str, Any],
        contract: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if result.get("sourceSplitFingerprint") != split.get("splitFingerprint"):
            raise ValueError("El readiness no corresponde al split producido.")
        if result.get("economicContractFingerprint") != contract.get(
            "economicContractFingerprint"
        ):
            raise ValueError("El readiness no corresponde al contrato económico producido.")
        if result.get("advisoryStatus") != "no_advice":
            raise ValueError("El pipeline debe permanecer en no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if result.get(field) is not False:
                raise ValueError(f"El pipeline intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if result.get(field) is not None:
                raise ValueError(f"El pipeline no puede definir {field}.")
        policy = result.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El pipeline no recibió política shadow.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("El pipeline consumió la reserva temporal futura.")
        if policy.get("thresholdFitting") != "not_performed":
            raise ValueError("El pipeline ajustó thresholds prematuramente.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El pipeline habilitó promoción automática.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El pipeline habilitó trading automático.")
