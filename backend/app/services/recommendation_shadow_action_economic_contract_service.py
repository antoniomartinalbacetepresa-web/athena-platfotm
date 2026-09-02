from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any


class RecommendationShadowActionEconomicContractService:
    """Build and validate immutable economic semantics for shadow action research.

    Cost and slippage values deliberately have no defaults: they must come from an
    explicitly precommitted research protocol. This service does not fit action
    thresholds, assign advice, promote models or enable execution.
    """

    ARTIFACT_VERSION = "shadow-action-economic-contract-v1"
    PORTFOLIO_MODEL = "long_only_single_asset_exposure"
    POSITION_STATES = ("flat", "long")
    ACTIONS = ("buy", "hold", "reduce", "sell")
    _ACTION_SEMANTICS = {
        "buy": {
            "meaning": "initiate_or_increase_long_exposure",
            "allowedFrom": ["flat", "long"],
            "requiresTrade": True,
        },
        "hold": {
            "meaning": "keep_current_exposure_unchanged",
            "allowedFrom": ["flat", "long"],
            "requiresTrade": False,
        },
        "reduce": {
            "meaning": "decrease_long_exposure_without_fully_exiting",
            "allowedFrom": ["long"],
            "requiresTrade": True,
        },
        "sell": {
            "meaning": "exit_long_exposure_to_flat",
            "allowedFrom": ["long"],
            "requiresTrade": True,
        },
    }
    _ROUND_TRIP_TREATMENT = "apply_explicit_costs_to_each_executed_trade_leg"
    _COST_SOURCE = "caller_precommitted_research_protocol"

    def build(
        self,
        *,
        transaction_cost_bps: float,
        slippage_bps: float,
        objective_name: str,
        objective_version: str,
    ) -> dict[str, Any]:
        transaction_cost = self._nonnegative_finite(
            transaction_cost_bps, "transaction_cost_bps"
        )
        slippage = self._nonnegative_finite(slippage_bps, "slippage_bps")
        objective = self._nonempty(objective_name, "objective_name")
        version = self._nonempty(objective_version, "objective_version")
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "portfolioModel": self.PORTFOLIO_MODEL,
            "positionStates": list(self.POSITION_STATES),
            "actions": deepcopy(self._ACTION_SEMANTICS),
            "economicObjective": {
                "name": objective,
                "version": version,
                "transactionCostBps": transaction_cost,
                "slippageBps": slippage,
                "roundTripCostTreatment": self._ROUND_TRIP_TREATMENT,
                "costAssumptionsSource": self._COST_SOURCE,
            },
            "constraints": {
                "shortSellingAllowed": False,
                "leverageAllowed": False,
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "thresholdFittingPerformed": False,
                "futureTemporalReserveConsumed": False,
            },
        }
        return {
            **core,
            "economicContractFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
        }

    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("El contrato económico debe ser un objeto.")
        expected = self._sha256(
            artifact.get("economicContractFingerprint"), "economicContractFingerprint"
        )
        core_keys = (
            "artifactVersion",
            "portfolioModel",
            "positionStates",
            "actions",
            "economicObjective",
            "constraints",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != expected:
            raise ValueError("El fingerprint del contrato económico no coincide.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de contrato económico no soportada.")
        if artifact.get("portfolioModel") != self.PORTFOLIO_MODEL:
            raise ValueError("El modelo de cartera del contrato no está permitido.")
        if artifact.get("positionStates") != list(self.POSITION_STATES):
            raise ValueError("Los estados de posición del contrato fueron alterados.")
        if artifact.get("actions") != self._ACTION_SEMANTICS:
            raise ValueError("La semántica exacta de acciones fue alterada.")

        objective = artifact.get("economicObjective")
        if not isinstance(objective, dict):
            raise ValueError("Falta el objetivo económico preespecificado.")
        self._nonempty(objective.get("name"), "economicObjective.name")
        self._nonempty(objective.get("version"), "economicObjective.version")
        self._nonnegative_finite(
            objective.get("transactionCostBps"), "economicObjective.transactionCostBps"
        )
        self._nonnegative_finite(
            objective.get("slippageBps"), "economicObjective.slippageBps"
        )
        if objective.get("roundTripCostTreatment") != self._ROUND_TRIP_TREATMENT:
            raise ValueError("El tratamiento de costes fue alterado.")
        if objective.get("costAssumptionsSource") != self._COST_SOURCE:
            raise ValueError("La procedencia de los costes no está precomprometida.")
        expected_objective_keys = {
            "name",
            "version",
            "transactionCostBps",
            "slippageBps",
            "roundTripCostTreatment",
            "costAssumptionsSource",
        }
        if set(objective) != expected_objective_keys:
            raise ValueError("El objetivo económico contiene campos no permitidos.")

        constraints = artifact.get("constraints")
        required_false = {
            "shortSellingAllowed",
            "leverageAllowed",
            "automaticTrading",
            "automaticProductionPromotion",
            "thresholdFittingPerformed",
            "futureTemporalReserveConsumed",
        }
        if not isinstance(constraints, dict) or set(constraints) != required_false:
            raise ValueError("Las restricciones del contrato fueron alteradas.")
        if any(constraints.get(field) is not False for field in required_false):
            raise ValueError("El contrato económico intenta habilitar una capacidad prohibida.")

        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"{field} debe permanecer deshabilitado.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if artifact.get(field) is not None:
                raise ValueError(f"{field} no puede estar definido en el contrato económico.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("El contrato económico debe permanecer en no_advice.")
        return artifact

    def _nonnegative_finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser un número finito no negativo.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser un número finito no negativo.") from exc
        if not math.isfinite(result) or result < 0.0:
            raise ValueError(f"{field} debe ser un número finito no negativo.")
        return result

    def _nonempty(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} no puede estar vacío.")
        return result

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
