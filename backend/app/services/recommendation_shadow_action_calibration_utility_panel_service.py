from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_integrity_service import (
    RecommendationShadowActionCalibrationIntegrityService,
)
from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_shadow_action_economic_utility_service import (
    RecommendationShadowActionEconomicUtilityService,
)


class _SplitValidator(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _SemanticValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _ContractValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _UtilityService(Protocol):
    def evaluate(
        self,
        *,
        economic_contract: dict[str, Any],
        current_state: str,
        realized_excess_return: float,
    ) -> dict[str, Any]: ...


class RecommendationShadowActionCalibrationUtilityPanelService:
    """Create state-complete counterfactual labels from matured PIT split rows.

    No historical portfolio path is fabricated. Each already-matured train or
    validation row is evaluated independently under every state defined by the
    frozen economic contract. That yields state-conditional counterfactual utility
    labels for later policy research while preserving the untouched future reserve.
    """

    ARTIFACT_VERSION = "shadow-action-calibration-utility-panel-v1"

    def __init__(
        self,
        *,
        split_validator: _SplitValidator | None = None,
        semantic_validator: _SemanticValidator | None = None,
        contract_validator: _ContractValidator | None = None,
        utility_service: _UtilityService | None = None,
    ) -> None:
        self._split_validator = split_validator or RecommendationShadowActionCalibrationSplitService()
        self._semantic_validator = semantic_validator or RecommendationShadowActionCalibrationIntegrityService()
        self._contract_validator = contract_validator or RecommendationShadowActionEconomicContractService()
        self._utility_service = utility_service or RecommendationShadowActionEconomicUtilityService()

    def build(
        self,
        *,
        split: dict[str, Any],
        economic_contract: dict[str, Any],
    ) -> dict[str, Any]:
        if self._split_validator.validate_artifact(split) is not split:
            raise ValueError("El validador de split sustituyó el artefacto.")
        if self._semantic_validator.validate(split) is not split:
            raise ValueError("El validador semántico sustituyó el split.")
        if self._contract_validator.validate(economic_contract) is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")

        states = economic_contract.get("positionStates")
        if not isinstance(states, dict) or not states:
            raise ValueError("El contrato económico no contiene estados.")
        state_names = list(states.keys())
        train_rows = self._rows(split.get("trainRows"), "trainRows")
        validation_rows = self._rows(split.get("validationRows"), "validationRows")

        train_panel = self._partition_panel(
            rows=train_rows,
            states=state_names,
            economic_contract=economic_contract,
            partition="train",
        )
        validation_panel = self._partition_panel(
            rows=validation_rows,
            states=state_names,
            economic_contract=economic_contract,
            partition="validation",
        )
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceSplitFingerprint": self._sha256(
                split.get("splitFingerprint"), "splitFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                economic_contract.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "positionStates": state_names,
            "requestedHorizons": list(split.get("requestedHorizons") or []),
            "trainSourceRowCount": len(train_rows),
            "validationSourceRowCount": len(validation_rows),
            "trainUtilityRowCount": len(train_panel),
            "validationUtilityRowCount": len(validation_panel),
            "sourceReservedFutureRowCount": self._nonnegative_int(
                split.get("reservedFutureRowCount"), "reservedFutureRowCount"
            ),
            "trainUtilityRows": train_panel,
            "validationUtilityRows": validation_panel,
        }
        return {
            "status": (
                "shadow_action_calibration_utility_panel_available"
                if train_panel and validation_panel
                else "shadow_action_calibration_utility_panel_insufficient"
            ),
            **core,
            "utilityPanelFingerprint": self._fingerprint(core),
            "labelSemantics": "matured_outcome_state_counterfactuals_not_observed_portfolio_history",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "portfolioHistoryFabricated": False,
                "allContractStatesEvaluatedPerMaturedRow": True,
                "futureReserveConsumed": False,
                "thresholdFitting": "not_performed",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _partition_panel(
        self,
        *,
        rows: list[dict[str, Any]],
        states: list[str],
        economic_contract: dict[str, Any],
        partition: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            expected = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            realized = self._finite(row.get("realizedExcessReturn"), "realizedExcessReturn")
            candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            for state in states:
                utility = self._utility_service.evaluate(
                    economic_contract=economic_contract,
                    current_state=state,
                    realized_excess_return=realized,
                )
                if utility.get("currentState") != state:
                    raise ValueError("El evaluador devolvió un estado distinto al solicitado.")
                if utility.get("advisoryStatus") != "no_advice" or utility.get("action") is not None:
                    raise ValueError("El evaluador contrafactual intentó publicar consejo.")
                result.append(
                    {
                        "partition": partition,
                        "candidateId": candidate_id,
                        "symbol": row.get("symbol"),
                        "horizonDays": horizon,
                        "candidateAsOf": row.get("candidateAsOf"),
                        "outcomeDueAt": row.get("outcomeDueAt"),
                        "outcomeEvaluatedAt": row.get("outcomeEvaluatedAt"),
                        "expectedExcessReturn": expected,
                        "realizedExcessReturn": realized,
                        "currentState": state,
                        "utilityFingerprint": self._sha256(
                            utility.get("utilityFingerprint"), "utilityFingerprint"
                        ),
                        "allowedActionUtilities": utility.get("allowedActionUtilities"),
                        "hindsightBestActions": utility.get("hindsightBestActions"),
                    }
                )
        return result

    def _rows(self, value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"{field} debe ser una lista.")
        if any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{field} contiene una fila inválida.")
        return list(value)

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _nonnegative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} debe ser entero no negativo.")
        return value

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
