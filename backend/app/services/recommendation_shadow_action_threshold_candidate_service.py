from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_utility_panel_service import (
    RecommendationShadowActionCalibrationUtilityPanelService,
)


class _PanelValidator(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionThresholdCandidateService:
    """Generate state-conditional threshold candidates from TRAIN signal only.

    Candidate cut points are derived solely from the distribution of
    ``expectedExcessReturn`` in train rows. Realized train utility and every
    validation field are deliberately ignored. A later service must select among
    these pre-generated policies using validation only; this service never selects
    or promotes one.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-candidates-v1"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(
        self,
        *,
        panel_validator: _PanelValidator | None = None,
        max_grid_points: int = 11,
    ) -> None:
        if isinstance(max_grid_points, bool) or not isinstance(max_grid_points, int):
            raise ValueError("max_grid_points debe ser entero.")
        if max_grid_points < 2 or max_grid_points > 51:
            raise ValueError("max_grid_points debe estar entre 2 y 51.")
        self._panel_validator = panel_validator or RecommendationShadowActionCalibrationUtilityPanelService()
        self._max_grid_points = max_grid_points

    def generate(self, utility_panel: dict[str, Any]) -> dict[str, Any]:
        if self._panel_validator.validate_artifact(utility_panel) is not utility_panel:
            raise ValueError("El validador sustituyó el panel de utilidad.")
        if utility_panel.get("positionStates") != list(self.STATES):
            raise ValueError("El generador exige el contrato económico v2 de tres estados.")
        train_rows = self._rows(utility_panel.get("trainUtilityRows"), "trainUtilityRows")
        requested = self._horizons(utility_panel.get("requestedHorizons"))

        unique_signal_by_horizon: dict[int, set[float]] = defaultdict(set)
        seen_source_row: set[tuple[int, int]] = set()
        for row in train_rows:
            candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            if horizon not in requested:
                raise ValueError("trainUtilityRows contiene un horizonte no solicitado.")
            state = str(row.get("currentState") or "")
            if state not in self.STATES:
                raise ValueError("trainUtilityRows contiene un estado no permitido.")
            signal = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            source_identity = (candidate_id, horizon)
            # Each source row is repeated once per state. Signal collection is
            # de-duplicated by candidate/horizon so state expansion cannot distort
            # the train-derived grid.
            if source_identity not in seen_source_row:
                unique_signal_by_horizon[horizon].add(signal)
                seen_source_row.add(source_identity)

        horizon_payloads: dict[str, Any] = {}
        total_candidates = 0
        for horizon in requested:
            all_signals = sorted(unique_signal_by_horizon.get(horizon, set()))
            grid = self._bounded_grid(all_signals)
            policies: list[dict[str, Any]] = []
            for threshold in grid:
                policies.append(
                    self._policy(
                        horizon=horizon,
                        state="flat",
                        thresholds={"buyAtOrAbove": threshold},
                        rule="buy_if_signal_gte_buy_threshold_else_hold",
                    )
                )
            if len(grid) >= 2:
                for low_index, low in enumerate(grid[:-1]):
                    for high in grid[low_index + 1 :]:
                        policies.append(
                            self._policy(
                                horizon=horizon,
                                state="reduced_long",
                                thresholds={
                                    "sellAtOrBelow": low,
                                    "buyAtOrAbove": high,
                                },
                                rule=(
                                    "sell_if_signal_lte_sell_threshold_buy_if_signal_gte_"
                                    "buy_threshold_else_hold"
                                ),
                            )
                        )
                        policies.append(
                            self._policy(
                                horizon=horizon,
                                state="full_long",
                                thresholds={
                                    "sellAtOrBelow": low,
                                    "reduceAtOrBelow": high,
                                },
                                rule=(
                                    "sell_if_signal_lte_sell_threshold_reduce_if_signal_lte_"
                                    "reduce_threshold_else_hold"
                                ),
                            )
                        )
            counts = {
                state: sum(1 for policy in policies if policy["currentState"] == state)
                for state in self.STATES
            }
            horizon_payloads[str(horizon)] = {
                "horizonDays": horizon,
                "uniqueTrainSignalCount": len(all_signals),
                "trainSignalGrid": grid,
                "candidatePolicyCount": len(policies),
                "candidatePolicyCountByState": counts,
                "allStatesHaveCandidates": all(counts[state] > 0 for state in self.STATES),
                "candidatePolicies": policies,
            }
            total_candidates += len(policies)

        all_horizons_have_candidates = all(
            payload["allStatesHaveCandidates"] for payload in horizon_payloads.values()
        )
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceUtilityPanelFingerprint": self._sha256(
                utility_panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                utility_panel.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "requestedHorizons": requested,
            "maxGridPoints": self._max_grid_points,
            "candidatePolicyCount": total_candidates,
            "allRequestedHorizonsHaveStateCompleteCandidates": all_horizons_have_candidates,
            "horizons": horizon_payloads,
        }
        return {
            "status": (
                "shadow_action_threshold_candidates_available"
                if all_horizons_have_candidates
                else "shadow_action_threshold_candidates_insufficient"
            ),
            **core,
            "candidateSetFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "selectedPolicy": None,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "candidateThresholdSource": "train_expected_excess_return_distribution_only",
                "trainRealizedOutcomesUsedForCandidateGeneration": False,
                "validationDataAccessedForCandidateGeneration": False,
                "candidateSelection": "not_performed",
                "futureReserveConsumed": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _bounded_grid(self, values: list[float]) -> list[float]:
        if len(values) <= self._max_grid_points:
            return list(values)
        selected: list[float] = []
        last_index = len(values) - 1
        for i in range(self._max_grid_points):
            index = round(i * last_index / (self._max_grid_points - 1))
            value = values[index]
            if not selected or value != selected[-1]:
                selected.append(value)
        return selected

    def _policy(
        self,
        *,
        horizon: int,
        state: str,
        thresholds: dict[str, float],
        rule: str,
    ) -> dict[str, Any]:
        core = {
            "horizonDays": horizon,
            "currentState": state,
            "thresholds": thresholds,
            "decisionRule": rule,
        }
        return {**core, "policyFingerprint": self._fingerprint(core)}

    def _rows(self, value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"{field} debe ser una lista.")
        if any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{field} contiene una fila inválida.")
        return list(value)

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requestedHorizons debe ser una lista no vacía.")
        result: list[int] = []
        seen: set[int] = set()
        for raw in value:
            horizon = self._positive_int(raw, "requestedHorizons")
            if horizon in seen:
                raise ValueError("requestedHorizons contiene duplicados.")
            seen.add(horizon)
            result.append(horizon)
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

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
