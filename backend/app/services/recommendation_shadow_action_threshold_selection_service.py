from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_utility_panel_service import (
    RecommendationShadowActionCalibrationUtilityPanelService,
)
from app.services.recommendation_shadow_action_threshold_candidate_service import (
    RecommendationShadowActionThresholdCandidateService,
)


class _PanelValidator(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _CandidateService(Protocol):
    def generate(self, utility_panel: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionThresholdSelectionService:
    """Select pre-generated threshold policies using VALIDATION utility only.

    The candidate service is invoked internally, so callers cannot inject a
    validation-optimized threshold. Candidate generation remains train-signal-only;
    this service then scores exactly those candidates on validation counterfactual
    utility. The selected research policies remain shadow and must be confirmed on
    a still-unseen future temporal reserve before any advisory use.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-selection-v1"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(
        self,
        *,
        panel_validator: _PanelValidator | None = None,
        candidate_service: _CandidateService | None = None,
        min_validation_rows_per_state: int = 10,
    ) -> None:
        if (
            isinstance(min_validation_rows_per_state, bool)
            or not isinstance(min_validation_rows_per_state, int)
            or min_validation_rows_per_state < 1
        ):
            raise ValueError("min_validation_rows_per_state debe ser entero positivo.")
        self._panel_validator = panel_validator or RecommendationShadowActionCalibrationUtilityPanelService()
        self._candidate_service = candidate_service or RecommendationShadowActionThresholdCandidateService()
        self._min_validation_rows = min_validation_rows_per_state

    def select(self, utility_panel: dict[str, Any]) -> dict[str, Any]:
        if self._panel_validator.validate_artifact(utility_panel) is not utility_panel:
            raise ValueError("El validador sustituyó el panel de utilidad.")
        candidates = self._candidate_service.generate(utility_panel)
        self._assert_candidate_contract(candidates, utility_panel)

        validation_rows = self._rows(
            utility_panel.get("validationUtilityRows"), "validationUtilityRows"
        )
        grouped_validation = self._group_validation_rows(validation_rows)
        requested = self._horizons(utility_panel.get("requestedHorizons"))
        candidate_horizons = candidates.get("horizons")
        if not isinstance(candidate_horizons, dict):
            raise ValueError("El conjunto candidato carece de horizons.")

        selections: dict[str, Any] = {}
        all_complete = True
        for horizon in requested:
            candidate_payload = candidate_horizons.get(str(horizon))
            if not isinstance(candidate_payload, dict):
                raise ValueError("Faltan candidatos para un horizonte solicitado.")
            policies = candidate_payload.get("candidatePolicies")
            if not isinstance(policies, list):
                raise ValueError("candidatePolicies debe ser una lista.")
            state_selections: dict[str, Any] = {}
            for state in self.STATES:
                rows = grouped_validation.get((horizon, state), [])
                state_policies = [
                    policy
                    for policy in policies
                    if isinstance(policy, dict) and policy.get("currentState") == state
                ]
                if len(rows) < self._min_validation_rows or not state_policies:
                    state_selections[state] = {
                        "status": "insufficient_validation_for_threshold_selection",
                        "validationRowCount": len(rows),
                        "minimumValidationRowsRequired": self._min_validation_rows,
                        "candidatePolicyCount": len(state_policies),
                        "selectedPolicy": None,
                    }
                    all_complete = False
                    continue
                scored = [self._score_policy(policy, rows) for policy in state_policies]
                scored.sort(
                    key=lambda item: (
                        -item["meanNetRealizedExcessUtility"],
                        item["nonHoldDecisionRate"],
                        item["policyFingerprint"],
                    )
                )
                selected = scored[0]
                state_selections[state] = {
                    "status": "validation_selected_shadow_policy",
                    "validationRowCount": len(rows),
                    "minimumValidationRowsRequired": self._min_validation_rows,
                    "candidatePolicyCount": len(state_policies),
                    "selectionObjective": (
                        "maximize_mean_net_realized_excess_utility_then_minimize_non_hold_rate_"
                        "then_policy_fingerprint"
                    ),
                    "selectedPolicy": selected,
                }
            selections[str(horizon)] = {
                "horizonDays": horizon,
                "states": state_selections,
                "allStatesSelected": all(
                    payload.get("selectedPolicy") is not None
                    for payload in state_selections.values()
                ),
            }
            if not selections[str(horizon)]["allStatesSelected"]:
                all_complete = False

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceUtilityPanelFingerprint": self._sha256(
                utility_panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
            ),
            "candidateSetFingerprint": self._sha256(
                candidates.get("candidateSetFingerprint"), "candidateSetFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                utility_panel.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "requestedHorizons": requested,
            "minimumValidationRowsPerState": self._min_validation_rows,
            "allRequestedHorizonsAndStatesSelected": all_complete,
            "selections": selections,
        }
        return {
            "status": (
                "shadow_action_threshold_selection_frozen_for_future_confirmation"
                if all_complete
                else "shadow_action_threshold_selection_insufficient"
            ),
            **core,
            "selectionFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "futureReserveConfirmationEligible": all_complete,
            "policy": {
                "candidateGenerationPartition": "train_signal_only",
                "candidateSelectionPartition": "validation_only",
                "trainRealizedOutcomesUsedForSelection": False,
                "futureReserveConsumed": False,
                "selectedResearchThresholdsMayBeRefitOnFutureReserve": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _group_validation_rows(
        self, rows: list[dict[str, Any]]
    ) -> dict[tuple[int, str], list[dict[str, Any]]]:
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        source_identity_states: dict[tuple[int, int], set[str]] = defaultdict(set)
        source_identity_signal: dict[tuple[int, int], float] = {}
        for row in rows:
            candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            state = str(row.get("currentState") or "")
            if state not in self.STATES:
                raise ValueError("Validation contiene un estado no permitido.")
            signal = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            identity = (candidate_id, horizon)
            if state in source_identity_states[identity]:
                raise ValueError("Validation contiene un estado duplicado para una fila fuente.")
            source_identity_states[identity].add(state)
            existing_signal = source_identity_signal.get(identity)
            if existing_signal is None:
                source_identity_signal[identity] = signal
            elif existing_signal != signal:
                raise ValueError("Validation contiene señales inconsistentes entre estados.")
            grouped[(horizon, state)].append(row)
        expected_states = set(self.STATES)
        if any(states != expected_states for states in source_identity_states.values()):
            raise ValueError("Validation no contiene exactamente todos los estados por fila fuente.")
        return grouped

    def _score_policy(
        self, policy: dict[str, Any], rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        policy_fingerprint = self._sha256(
            policy.get("policyFingerprint"), "policyFingerprint"
        )
        state = str(policy.get("currentState") or "")
        net_values: list[float] = []
        regrets: list[float] = []
        non_hold = 0
        action_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.get("currentState") != state:
                raise ValueError("Una política recibió validation de otro estado.")
            signal = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            action = self._decide(policy, signal)
            utilities = row.get("allowedActionUtilities")
            if not isinstance(utilities, dict) or action not in utilities:
                raise ValueError("La política eligió una acción sin utilidad permitida.")
            selected_payload = utilities[action]
            if not isinstance(selected_payload, dict):
                raise ValueError("La utilidad seleccionada tiene formato inválido.")
            selected_net = self._finite(
                selected_payload.get("netRealizedExcessUtility"),
                "netRealizedExcessUtility",
            )
            all_nets = []
            for payload in utilities.values():
                if not isinstance(payload, dict):
                    raise ValueError("Una utilidad permitida tiene formato inválido.")
                all_nets.append(
                    self._finite(
                        payload.get("netRealizedExcessUtility"),
                        "netRealizedExcessUtility",
                    )
                )
            best_net = max(all_nets)
            net_values.append(selected_net)
            regrets.append(best_net - selected_net)
            action_counts[action] += 1
            if action != "hold":
                non_hold += 1
        count = len(rows)
        return {
            "policyFingerprint": policy_fingerprint,
            "currentState": state,
            "thresholds": policy.get("thresholds"),
            "decisionRule": policy.get("decisionRule"),
            "validationRowCount": count,
            "meanNetRealizedExcessUtility": sum(net_values) / count,
            "meanHindsightRegret": sum(regrets) / count,
            "nonHoldDecisionRate": non_hold / count,
            "actionCounts": dict(sorted(action_counts.items())),
        }

    def _decide(self, policy: dict[str, Any], signal: float) -> str:
        state = str(policy.get("currentState") or "")
        thresholds = policy.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("La política carece de thresholds.")
        if state == "flat":
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            return "buy" if signal >= buy else "hold"
        if state == "reduced_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            if not sell < buy:
                raise ValueError("La política reduced_long no mantiene sell < buy.")
            if signal <= sell:
                return "sell"
            if signal >= buy:
                return "buy"
            return "hold"
        if state == "full_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            reduce = self._finite(thresholds.get("reduceAtOrBelow"), "reduceAtOrBelow")
            if not sell < reduce:
                raise ValueError("La política full_long no mantiene sell < reduce.")
            if signal <= sell:
                return "sell"
            if signal <= reduce:
                return "reduce"
            return "hold"
        raise ValueError("Estado de política no soportado.")

    def _assert_candidate_contract(
        self, candidates: dict[str, Any], utility_panel: dict[str, Any]
    ) -> None:
        if not isinstance(candidates, dict):
            raise ValueError("El conjunto candidato debe ser un objeto.")
        if candidates.get("sourceUtilityPanelFingerprint") != utility_panel.get(
            "utilityPanelFingerprint"
        ):
            raise ValueError("Los candidatos no pertenecen al panel suministrado.")
        if candidates.get("economicContractFingerprint") != utility_panel.get(
            "economicContractFingerprint"
        ):
            raise ValueError("Los candidatos no pertenecen al contrato económico.")
        if candidates.get("advisoryStatus") != "no_advice":
            raise ValueError("Los candidatos deben permanecer en no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if candidates.get(field) is not False:
                raise ValueError(f"Los candidatos intentaron habilitar {field}.")
        if candidates.get("selectedPolicy") is not None or candidates.get("action") is not None:
            raise ValueError("El generador candidato no puede preseleccionar una acción/política.")
        candidate_policy = candidates.get("policy")
        if not isinstance(candidate_policy, dict):
            raise ValueError("Los candidatos carecen de policy.")
        if candidate_policy.get("validationDataAccessedForCandidateGeneration") is not False:
            raise ValueError("La generación candidata accedió a validation.")
        if candidate_policy.get("trainRealizedOutcomesUsedForCandidateGeneration") is not False:
            raise ValueError("La generación candidata utilizó outcomes de train.")
        if candidate_policy.get("futureReserveConsumed") is not False:
            raise ValueError("La generación candidata consumió la reserva futura.")

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
