from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any


class RecommendationShadowProtocolSelectionService:
    """Select a final ridge protocol using research-era validation choices only.

    Each walk-forward fold already selects ``ridgeLambda`` from its validation
    partition before the fold test is evaluated. This service aggregates only
    those validation-era selections. It deliberately ignores fold test MSE,
    sign accuracy and baseline wins so the final pre-holdout lambda cannot be
    chosen retrospectively from test performance.

    The modal validation-selected lambda is used. Ties are resolved toward the
    larger lambda (stronger regularization) as a deterministic conservative
    rule. The result remains shadow research evidence and can never assign an
    investment action or become production eligible.
    """

    SELECTION_VERSION = "shadow-ridge-protocol-selection-v1"

    def __init__(self, *, minimum_evaluated_folds: int = 3) -> None:
        if minimum_evaluated_folds < 2:
            raise ValueError("minimum_evaluated_folds debe ser al menos 2.")
        self._minimum_evaluated_folds = int(minimum_evaluated_folds)

    def select(
        self,
        *,
        walk_forward_evidence: dict[str, Any],
        horizon_days: int,
    ) -> dict[str, Any]:
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")
        self._assert_shadow(walk_forward_evidence, "walk_forward_evidence")
        if walk_forward_evidence.get("status") != "shadow_walk_forward_evaluated":
            raise ValueError("Se requiere evidencia shadow_walk_forward_evaluated.")

        reported_horizon = self._positive_int(
            walk_forward_evidence.get("horizonDays"), "walk_forward_evidence.horizonDays"
        )
        if reported_horizon != int(horizon_days):
            raise ValueError("El horizonte de la evidencia walk-forward no coincide.")

        folds = walk_forward_evidence.get("folds")
        if not isinstance(folds, list):
            raise ValueError("walk_forward_evidence.folds debe ser una lista.")

        selections: list[dict[str, Any]] = []
        for position, fold in enumerate(folds):
            if not isinstance(fold, dict):
                raise ValueError(f"folds[{position}] debe ser un objeto.")
            evaluation = fold.get("evaluation")
            if not isinstance(evaluation, dict):
                raise ValueError(f"folds[{position}].evaluation debe ser un objeto.")
            self._assert_shadow(evaluation, f"folds[{position}].evaluation")
            if evaluation.get("status") != "shadow_linear_candidate_evaluated":
                continue

            evaluation_horizon = evaluation.get("horizonDays")
            if evaluation_horizon is not None and self._positive_int(
                evaluation_horizon, f"folds[{position}].evaluation.horizonDays"
            ) != int(horizon_days):
                raise ValueError("Un fold evaluado cambió de horizonte.")

            selection = evaluation.get("selection")
            if not isinstance(selection, dict):
                raise ValueError(f"folds[{position}] no contiene selection válida.")
            if selection.get("criterion") != "minimum_validation_mse":
                raise ValueError("La selección por fold debe proceder de validation MSE.")
            ridge_lambda = self._finite_non_negative(
                selection.get("ridgeLambda"), f"folds[{position}].selection.ridgeLambda"
            )

            candidates = selection.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                raise ValueError("La selección por fold debe conservar candidatos de validación.")
            candidate_lambdas = {
                self._finite_non_negative(
                    candidate.get("ridgeLambda") if isinstance(candidate, dict) else None,
                    f"folds[{position}].selection.candidates.ridgeLambda",
                )
                for candidate in candidates
            }
            if ridge_lambda not in candidate_lambdas:
                raise ValueError("ridgeLambda seleccionado no pertenece a sus candidatos.")

            selections.append(
                {
                    "foldIndex": self._non_negative_int(
                        fold.get("foldIndex", position), f"folds[{position}].foldIndex"
                    ),
                    "ridgeLambda": ridge_lambda,
                    "selectionCriterion": "minimum_validation_mse",
                }
            )

        if len(selections) < self._minimum_evaluated_folds:
            return {
                "status": "insufficient_protocol_selection_evidence",
                "selectionVersion": self.SELECTION_VERSION,
                "horizonDays": int(horizon_days),
                "evaluatedFoldSelectionCount": len(selections),
                "minimumEvaluatedFolds": self._minimum_evaluated_folds,
                "foldSelections": selections,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": self._policy(),
            }

        counts = Counter(item["ridgeLambda"] for item in selections)
        highest_count = max(counts.values())
        tied_modes = sorted(
            (ridge_lambda for ridge_lambda, count in counts.items() if count == highest_count),
            reverse=True,
        )
        selected_lambda = float(tied_modes[0])
        support_ratio = highest_count / len(selections)

        core = {
            "selectionVersion": self.SELECTION_VERSION,
            "horizonDays": int(horizon_days),
            "selectionRule": "modal_validation_selected_lambda_stronger_regularization_on_tie",
            "selectedRidgeLambda": selected_lambda,
            "evaluatedFoldSelectionCount": len(selections),
            "selectedFoldCount": highest_count,
            "selectionSupportRatio": support_ratio,
            "tieCount": len(tied_modes),
            "lambdaCounts": [
                {"ridgeLambda": float(ridge_lambda), "count": int(counts[ridge_lambda])}
                for ridge_lambda in sorted(counts)
            ],
            "foldSelections": selections,
            "testMetricsUsedForSelection": False,
        }
        return {
            "status": "shadow_ridge_protocol_selected",
            **core,
            "selectionFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def validate_selection(self, selection: dict[str, Any]) -> dict[str, Any]:
        if selection.get("status") != "shadow_ridge_protocol_selected":
            raise ValueError("Se requiere una selección shadow_ridge_protocol_selected.")
        self._assert_shadow(selection, "protocol_selection")
        if selection.get("selectionVersion") != self.SELECTION_VERSION:
            raise ValueError("Versión de protocol selection no compatible.")
        if selection.get("selectionRule") != (
            "modal_validation_selected_lambda_stronger_regularization_on_tie"
        ):
            raise ValueError("La regla de selección fue modificada.")
        if selection.get("testMetricsUsedForSelection") is not False:
            raise ValueError("La selección no puede utilizar métricas de test.")

        horizon_days = self._positive_int(selection.get("horizonDays"), "horizonDays")
        selected_lambda = self._finite_non_negative(
            selection.get("selectedRidgeLambda"), "selectedRidgeLambda"
        )
        fold_selections = selection.get("foldSelections")
        if not isinstance(fold_selections, list) or len(fold_selections) < self._minimum_evaluated_folds:
            raise ValueError("La selección no conserva suficientes folds.")

        normalized = []
        for position, item in enumerate(fold_selections):
            if not isinstance(item, dict):
                raise ValueError("foldSelections contiene un elemento inválido.")
            if item.get("selectionCriterion") != "minimum_validation_mse":
                raise ValueError("foldSelections contiene una selección no basada en validation.")
            normalized.append(
                {
                    "foldIndex": self._non_negative_int(
                        item.get("foldIndex"), f"foldSelections[{position}].foldIndex"
                    ),
                    "ridgeLambda": self._finite_non_negative(
                        item.get("ridgeLambda"), f"foldSelections[{position}].ridgeLambda"
                    ),
                    "selectionCriterion": "minimum_validation_mse",
                }
            )

        counts = Counter(item["ridgeLambda"] for item in normalized)
        highest_count = max(counts.values())
        tied_modes = sorted(
            (ridge_lambda for ridge_lambda, count in counts.items() if count == highest_count),
            reverse=True,
        )
        expected_lambda = float(tied_modes[0])
        if selected_lambda != expected_lambda:
            raise ValueError("selectedRidgeLambda no coincide con la regla determinista.")

        core = {
            "selectionVersion": self.SELECTION_VERSION,
            "horizonDays": horizon_days,
            "selectionRule": selection.get("selectionRule"),
            "selectedRidgeLambda": selected_lambda,
            "evaluatedFoldSelectionCount": len(normalized),
            "selectedFoldCount": highest_count,
            "selectionSupportRatio": highest_count / len(normalized),
            "tieCount": len(tied_modes),
            "lambdaCounts": [
                {"ridgeLambda": float(ridge_lambda), "count": int(counts[ridge_lambda])}
                for ridge_lambda in sorted(counts)
            ],
            "foldSelections": normalized,
            "testMetricsUsedForSelection": False,
        }
        if self._fingerprint(core) != selection.get("selectionFingerprint"):
            raise ValueError("La evidencia de protocol selection fue modificada.")
        return selection

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó el contrato no_advice.")

    def _positive_int(self, value: object, field: str) -> int:
        parsed = self._non_negative_int(value, field)
        if parsed <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return parsed

    def _non_negative_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed < 0:
            raise ValueError(f"{field} no puede ser negativo.")
        return parsed

    def _finite_non_negative(self, value: object, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{field} debe ser finito y no negativo.")
        return parsed

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _policy(self) -> dict[str, Any]:
        return {
            "lambdaEvidence": "validation_selected_lambda_per_walk_forward_fold_only",
            "foldTestMetricsUsedForLambdaSelection": False,
            "tieBreak": "stronger_regularization",
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
            "productionEligibility": False,
        }
