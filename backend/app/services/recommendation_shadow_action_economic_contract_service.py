from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any


class RecommendationShadowActionEconomicContractService:
    """Build and validate immutable economic semantics for shadow action research.

    Every quantity that affects economic utility is explicit: transaction cost,
    slippage and the reduced-position exposure fraction have no defaults. This
    service defines long-only state transitions but does not fit thresholds,
    publish advice, promote models or enable execution.
    """

    ARTIFACT_VERSION = "shadow-action-economic-contract-v2"
    PORTFOLIO_MODEL = "long_only_single_asset_target_exposure"
    POSITION_STATES = ("flat", "reduced_long", "full_long")
    ACTIONS = ("buy", "hold", "reduce", "sell")
    _ROUND_TRIP_TREATMENT = "apply_explicit_costs_pro_rata_to_absolute_exposure_change"
    _COST_SOURCE = "caller_precommitted_research_protocol"

    def build(
        self,
        *,
        transaction_cost_bps: float,
        slippage_bps: float,
        reduced_exposure_fraction: float,
        objective_name: str,
        objective_version: str,
    ) -> dict[str, Any]:
        transaction_cost = self._nonnegative_finite(
            transaction_cost_bps, "transaction_cost_bps"
        )
        slippage = self._nonnegative_finite(slippage_bps, "slippage_bps")
        reduced_exposure = self._open_unit_interval(
            reduced_exposure_fraction, "reduced_exposure_fraction"
        )
        objective = self._nonempty(objective_name, "objective_name")
        version = self._nonempty(objective_version, "objective_version")
        action_semantics = self._action_semantics(reduced_exposure)
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "portfolioModel": self.PORTFOLIO_MODEL,
            "positionStates": {
                "flat": {"targetExposureFraction": 0.0},
                "reduced_long": {"targetExposureFraction": reduced_exposure},
                "full_long": {"targetExposureFraction": 1.0},
            },
            "actions": action_semantics,
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

        states = artifact.get("positionStates")
        if not isinstance(states, dict) or set(states) != set(self.POSITION_STATES):
            raise ValueError("Los estados de posición del contrato fueron alterados.")
        if states.get("flat") != {"targetExposureFraction": 0.0}:
            raise ValueError("El estado flat fue alterado.")
        if states.get("full_long") != {"targetExposureFraction": 1.0}:
            raise ValueError("El estado full_long fue alterado.")
        reduced_payload = states.get("reduced_long")
        if not isinstance(reduced_payload, dict) or set(reduced_payload) != {
            "targetExposureFraction"
        }:
            raise ValueError("El estado reduced_long fue alterado.")
        reduced_exposure = self._open_unit_interval(
            reduced_payload.get("targetExposureFraction"),
            "positionStates.reduced_long.targetExposureFraction",
        )
        if artifact.get("actions") != self._action_semantics(reduced_exposure):
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

    def _action_semantics(self, reduced_exposure: float) -> dict[str, Any]:
        return {
            "buy": {
                "meaning": "enter_or_restore_full_long_target_exposure",
                "targetExposureFraction": 1.0,
                "requiresExistingPosition": False,
                "requiresTrade": True,
            },
            "hold": {
                "meaning": "preserve_current_target_exposure_without_trade",
                "targetExposureFraction": None,
                "requiresExistingPosition": False,
                "requiresTrade": False,
            },
            "reduce": {
                "meaning": "reduce_existing_long_target_exposure",
                "targetExposureFraction": reduced_exposure,
                "requiresExistingPosition": True,
                "requiresTrade": True,
            },
            "sell": {
                "meaning": "exit_any_long_target_exposure_to_flat",
                "targetExposureFraction": 0.0,
                "requiresExistingPosition": True,
                "requiresTrade": True,
            },
        }

    @classmethod
    def _fingerprint(cls, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        text = str(value or "").strip().lower()
        if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return text

    @staticmethod
    def _nonempty(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} no puede estar vacío.")
        return text

    @staticmethod
    def _nonnegative_finite(value: Any, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed) or parsed < 0.0:
            raise ValueError(f"{field} debe ser finito y no negativo.")
        return parsed

    @staticmethod
    def _open_unit_interval(value: Any, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed) or not 0.0 < parsed < 1.0:
            raise ValueError(f"{field} debe estar estrictamente entre 0 y 1.")
        return parsed
