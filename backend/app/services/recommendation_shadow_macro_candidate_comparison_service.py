from __future__ import annotations

import math
from typing import Any

from app.services.recommendation_shadow_linear_candidate_service import (
    RecommendationShadowLinearCandidateService,
)


class RecommendationShadowMacroCandidateComparisonService(
    RecommendationShadowLinearCandidateService
):
    """Compare the frozen base candidate with a research-only macro augmentation.

    The caller must provide the exact frozen split used by the base candidate and
    macro features preprocessed strictly inside that fold's training partition.
    This service never rebuilds the split, never reads persistence, never assigns
    actions, and never decides whether macro is "good enough". It only returns
    paired out-of-sample metrics and descriptive deltas on the same test rows.
    """

    SCHEMA_VERSION = "shadow-macro-candidate-comparison-v1"

    def compare(
        self,
        *,
        split: dict[str, Any],
        macro_preprocessing: dict[str, Any],
        base_evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(base_evaluation, dict) or base_evaluation.get("status") != (
            "shadow_linear_candidate_evaluated"
        ):
            return self._comparison_blocked("base_candidate_not_evaluated")
        if not isinstance(macro_preprocessing, dict) or macro_preprocessing.get(
            "status"
        ) != "shadow_macro_fold_preprocessing_fitted":
            return self._comparison_blocked(
                str(
                    (macro_preprocessing or {}).get("reason")
                    or "macro_preprocessing_not_fitted"
                )
            )
        if not isinstance(split, dict) or any(
            key not in split
            for key in ("train", "validation", "test", "counts", "featureSchemaVersion")
        ):
            return self._comparison_blocked(
                "frozen_split_missing_required_candidate_fields"
            )

        self._validate_frozen_split(split)
        selected_macro = list(macro_preprocessing.get("selectedFeatures") or [])
        if not selected_macro:
            return self._comparison_blocked("no_selected_macro_features")
        if len(set(selected_macro)) != len(selected_macro) or any(
            not isinstance(key, str) or not key.strip() for key in selected_macro
        ):
            raise ValueError("selectedFeatures macro contiene claves invalidas o duplicadas.")

        transformed = macro_preprocessing.get("partitions") or {}
        macro_vectors: dict[str, list[list[float]]] = {}
        for partition in ("train", "validation", "test"):
            source_rows = list(split[partition])
            transformed_rows = transformed.get(partition)
            if not isinstance(transformed_rows, list):
                raise ValueError(f"macro.partitions.{partition} debe ser una lista.")
            if len(transformed_rows) != len(source_rows):
                raise ValueError(
                    f"macro.partitions.{partition} no coincide con el split congelado."
                )
            vectors: list[list[float]] = []
            for index, (source, macro_row) in enumerate(
                zip(source_rows, transformed_rows)
            ):
                if not isinstance(source, dict) or not isinstance(macro_row, dict):
                    raise ValueError(
                        f"{partition}[{index}] no permite vincular identidad de fila."
                    )
                source_id = str(source.get("snapshotId") or "").strip()
                macro_id = str(macro_row.get("snapshotId") or "").strip()
                if not source_id or not macro_id or source_id != macro_id:
                    raise ValueError(
                        f"macro.partitions.{partition}[{index}] no coincide por snapshotId."
                    )
                raw_values = macro_row.get("values")
                if not isinstance(raw_values, dict):
                    raise ValueError(
                        f"macro.partitions.{partition}[{index}].values debe ser un mapa."
                    )
                vector: list[float] = []
                for key in selected_macro:
                    value = self._finite_float(raw_values.get(key))
                    if value is None:
                        raise ValueError(
                            f"macro.partitions.{partition}[{index}] carece de {key} finito."
                        )
                    vector.append(value)
                vectors.append(vector)
            macro_vectors[partition] = vectors

        train_rows = list(split["train"])
        validation_rows = list(split["validation"])
        test_rows = list(split["test"])
        insufficiencies = []
        for name, rows, minimum in (
            ("train", train_rows, self._minimum_train_rows),
            ("validation", validation_rows, self._minimum_validation_rows),
            ("test", test_rows, self._minimum_test_rows),
        ):
            if len(rows) < minimum:
                insufficiencies.append(
                    {"partition": name, "rowCount": len(rows), "minimum": minimum}
                )
        if insufficiencies:
            return self._comparison_blocked(
                "insufficient_shadow_calibration_data",
                details={"reasons": insufficiencies},
            )

        active_features, medians = self._fit_feature_schema(train_rows)
        if not active_features:
            return self._comparison_blocked("no_finite_base_features")
        train_raw = self._raw_matrix(train_rows, active_features, medians)
        means, scales, variable_indexes = self._fit_scaler(train_raw)
        if not variable_indexes:
            return self._comparison_blocked("all_base_features_constant")
        selected_base = [active_features[index] for index in variable_indexes]

        base_train_x = self._scaled_matrix(
            train_raw, means, scales, variable_indexes
        )
        base_validation_x = self._scaled_matrix(
            self._raw_matrix(validation_rows, active_features, medians),
            means,
            scales,
            variable_indexes,
        )
        base_test_x = self._scaled_matrix(
            self._raw_matrix(test_rows, active_features, medians),
            means,
            scales,
            variable_indexes,
        )
        train_x = [
            [*base_row, *macro_row]
            for base_row, macro_row in zip(base_train_x, macro_vectors["train"])
        ]
        validation_x = [
            [*base_row, *macro_row]
            for base_row, macro_row in zip(
                base_validation_x, macro_vectors["validation"]
            )
        ]
        test_x = [
            [*base_row, *macro_row]
            for base_row, macro_row in zip(base_test_x, macro_vectors["test"])
        ]
        if any(
            not math.isfinite(value)
            for matrix in (train_x, validation_x, test_x)
            for row in matrix
            for value in row
        ):
            raise ValueError("El diseno base+macro contiene valores no finitos.")

        train_y = self._targets(train_rows)
        validation_y = self._targets(validation_rows)
        test_y = self._targets(test_rows)
        candidates = []
        fitted_by_lambda: dict[float, list[float]] = {}
        for ridge_lambda in self._ridge_lambdas:
            coefficients = self._fit_ridge(train_x, train_y, ridge_lambda)
            fitted_by_lambda[ridge_lambda] = coefficients
            validation_predictions = self._predict(validation_x, coefficients)
            candidates.append(
                {
                    "ridgeLambda": ridge_lambda,
                    "validation": self._metrics(
                        validation_y, validation_predictions
                    ),
                }
            )
        selected = min(
            candidates,
            key=lambda item: (item["validation"]["mse"], item["ridgeLambda"]),
        )
        selected_lambda = float(selected["ridgeLambda"])
        coefficients = fitted_by_lambda[selected_lambda]
        augmented_test = self._metrics(
            test_y, self._predict(test_x, coefficients)
        )
        base_test = base_evaluation.get("test") or {}
        base_mse = self._required_finite(base_test.get("mse"), "base.test.mse")
        base_mae = self._required_finite(base_test.get("mae"), "base.test.mae")
        base_sign = self._required_finite(
            base_test.get("signAccuracy"), "base.test.signAccuracy"
        )
        deltas = {
            "mse": augmented_test["mse"] - base_mse,
            "mae": augmented_test["mae"] - base_mae,
            "signAccuracy": augmented_test["signAccuracy"] - base_sign,
        }
        if any(not math.isfinite(value) for value in deltas.values()):
            raise ValueError("La comparacion base+macro produjo un delta no finito.")

        feature_names = [
            *selected_base,
            *[f"macro::{key}" for key in selected_macro],
        ]
        return {
            "status": "shadow_macro_candidate_comparison_evaluated",
            "schemaVersion": self.SCHEMA_VERSION,
            "featureSchemaVersion": split["featureSchemaVersion"],
            "horizonDays": split.get("horizonDays"),
            "rowBinding": {
                "method": "exact_partition_order_and_snapshot_id",
                "partitionCounts": {
                    name: len(split[name]) for name in ("train", "validation", "test")
                },
                "sameFrozenSplit": True,
            },
            "selectedBaseFeatures": selected_base,
            "selectedMacroFeatures": selected_macro,
            "selection": {
                "criterion": "minimum_validation_mse",
                "ridgeLambda": selected_lambda,
                "candidates": candidates,
            },
            "model": {
                "intercept": coefficients[0],
                "standardizedCoefficients": {
                    feature: coefficients[index + 1]
                    for index, feature in enumerate(feature_names)
                },
            },
            "baseTest": {
                "mse": base_mse,
                "mae": base_mae,
                "signAccuracy": base_sign,
            },
            "augmentedTest": augmented_test,
            "deltaAugmentedMinusBase": deltas,
            "assessment": "not_assessed_without_precommitted_criteria",
            "thresholdApplied": False,
            "candidateInfluence": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "comparison": "paired_base_vs_base_plus_macro_same_frozen_rows",
                "macroPreprocessing": "provided_train_only_frozen_parameters",
                "train": "fit_coefficients_only_on_train",
                "validation": "ridge_selection_only",
                "test": "paired_final_metrics_only_after_selection",
                "thresholds": "none",
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "productionEligibility": False,
            },
        }

    def _comparison_blocked(
        self,
        reason: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "status": "insufficient_macro_candidate_comparison_data",
            "schemaVersion": self.SCHEMA_VERSION,
            "reason": reason,
            "assessment": "not_assessed_without_precommitted_criteria",
            "thresholdApplied": False,
            "candidateInfluence": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "comparison": "paired_only_no_fallback_to_unpaired_rows",
                "thresholds": "none",
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "productionEligibility": False,
            },
        }
        if details:
            result["details"] = details
        return result

    def _required_finite(self, value: object, field: str) -> float:
        parsed = self._finite_float(value)
        if parsed is None:
            raise ValueError(f"{field} debe ser finito para la comparacion pareada.")
        return parsed
