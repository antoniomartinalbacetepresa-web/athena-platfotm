from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class RecommendationShadowActionEconomicContractService:
    """Build an immutable, explicit economic contract for shadow action research.

    The contract defines BUY/HOLD/REDUCE/SELL relative to a long-only portfolio
    state and refuses to invent transaction-cost or slippage assumptions. Those
    values must be supplied explicitly by the research protocol and are then
    fingerprinted together with the action semantics.

    This artifact is research infrastructure only. It does not fit thresholds,
    assign actions to securities, promote models, or enable trading.
    """

    ARTIFACT_VERSION = "shadow-action-economic-contract-v1"
    ACTIONS = ("buy", "hold", "reduce", "sell")
    POSITION_STATES = ("flat", "long")

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
            "portfolioModel": "long_only_single_asset_exposure",
            "positionStates": list(self.POSITION_STATES),
            "actions": {
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
            },
            "economicObjective": {
                "name": objective,
                "version": version,
                "transactionCostBps": transaction_cost,
                "slippageBps": slippage,
                "roundTripCostTreatment": "apply_explicit_costs_to_each_executed_trade_leg",
                "costAssumptionsSource": "caller_precommitted_research_protocol",
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
        expected = artifact.get("economicContractFingerprint")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("economicContractFingerprint debe ser SHA-256 hexadecimal.")
        if any(char not in "0123456789abcdef" for char in expected.lower()):
            raise ValueError("economicContractFingerprint debe ser SHA-256 hexadecimal.")

        core_keys = (
            "artifactVersion",
            "portfolioModel",
            "positionStates",
            "actions",
            "economicObjective",
            "constraints",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != expected.lower():
            raise ValueError("El fingerprint del contrato económico no coincide.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de contrato económico no soportada.")
        if artifact.get("portfolioModel") != "long_only_single_asset_exposure":
            raise ValueError("El modelo de cartera del contrato no está permitido.")
        if artifact.get("positionStates") != list(self.POSITION_STATES):
            raise ValueError("Los estados de posición del contrato fueron alterados.")

        actions = artifact.get("actions")
        if not isinstance(actions, dict) or tuple(actions.keys()) != self.ACTIONS:
            raise ValueError("La semántica de acciones del contrato fue alterada.")
        expected_allowed = {
            "buy": ["flat", "long"],
            "hold": ["flat", "long"],
            "reduce": ["long"],
            "sell": ["long"],
        }
        for action, allowed in expected_allowed.items():
            payload = actions.get(action)
            if not isinstance(payload, dict) or payload.get("allowedFrom") != allowed:
                raise ValueError(f"Semántica inválida para {action}.")

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
        if objective.get("costAssumptionsSource") != "caller_precommitted_research_protocol":
            raise ValueError("La procedencia de los costes no está precomprometida.")

        constraints = artifact.get("constraints")
        required_false = (
            "shortSellingAllowed",
            "leverageAllowed",
            "automaticTrading",
            "automaticProductionPromotion",
            "thresholdFittingPerformed",
            "futureTemporalReserveConsumed",
        )
        if not isinstance(constraints, dict) or any(
            constraints.get(field) is not False for field in required_false
        ):
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

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
