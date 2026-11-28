from __future__ import annotations

import math
from statistics import median
from typing import Any

from app.services.recommendation_shadow_temporal_split_service import (
    RecommendationShadowTemporalSplitService,
)


class RecommendationShadowLinearCandidateService:
    """Evaluate a transparent ridge candidate on purged temporal partitions.

    The candidate predicts continuous benchmark-relative returns only. It never
    maps predictions to investment actions and can never become production
    eligible by itself.
    """

    FEATURE_NAMES = (
        "technicalScore",
        "riskScore",
        "return20d",
        "return60d",
        "annualizedVolatility",
        "maxDrawdown60d",
        "fundamentalCoverageRatio",
        "revenueGrowth",
        "netMargin",
        "liabilitiesToAssets",
        "reportedAnnualPe",
    )

    def __init__(
        self,
        *,
        split_service: RecommendationShadowTemporalSplitService | None = None,
        ridge_lambdas: tuple[float, ...] = (0.1, 1.0, 10.0),
        minimum_train_rows: int = 30,
        minimum_validation_rows: int = 10,
        minimum_test_rows: int = 10,
    ) -> None:
        if not ridge_lambdas or any(value < 0 for value in ridge_lambdas):
            raise ValueError("ridge_lambdas debe contener valores no negativos.")
        if min(minimum_train_rows, minimum_validation_rows, minimum_test_rows) <= 0:
            raise ValueError("Los mínimos de filas deben ser positivos.")
        self._split_service = (
            split_service
            if split_service is not None
            else RecommendationShadowTemporalSplitService()
        )
        self._ridge_lambdas = tuple(float(value) for value in ridge_lambdas)
        self._minimum_train_rows = int(minimum_train_rows)
        self._minimum_validation_rows = int(minimum_validation_rows)
        self._minimum_test_rows = int(minimum_test_rows)

    def evaluate(self, **split_kwargs: Any) -> dict[str, Any]:
        """Build one PIT split and evaluate it.

        This compatibility entry point owns split construction. Orchestrators
        that already froze a split must call ``evaluate_frozen_split`` instead
        so the evaluated universe cannot change between consumers.
        """
        split = self._split_service.build(require_benchmark=True, **split_kwargs)
        return self.evaluate_frozen_split(split=split)

    def evaluate_frozen_split(self, *, split: dict[str, Any]) -> dict[str, Any]:
        """Evaluate an already-built temporal split without reading persistence.

        The caller owns PIT construction and may safely reuse the exact same
        split for parallel research paths (for example base vs macro). This
        method intentionally performs no repository or split-service call.
        """
        self._validate_frozen_split(split)
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
            return self._blocked(split, insufficiencies)

        active_features, medians = self._fit_feature_schema(train_rows)
        if not active_features:
            return self._blocked(
                split,
                [{"partition": "train", "reason": "no_finite_features"}],
            )

        train_matrix = self._raw_matrix(train_rows, active_features, medians)
        means, scales, variable_indexes = self._fit_scaler(train_matrix)
        if not variable_indexes:
            return self._blocked(
                split,
                [{"partition": "train", "reason": "all_features_constant"}],
            )
        selected_features = [active_features[index] for index in variable_indexes]

        train_x = self._scaled_matrix(train_matrix, means, scales, variable_indexes)
        validation_x = self._scaled_matrix(
            self._raw_matrix(validation_rows, active_features, medians),
            means,
            scales,
            variable_indexes,
        )
        test_x = self._scaled_matrix(
            self._raw_matrix(test_rows, active_features, medians),
            means,
            scales,
            variable_indexes,
        )
        train_y = self._targets(train_rows)
        validation_y = self._targets(validation_rows)
        test_y = self._targets(test_rows)

        candidates = []
        fitted_by_lambda: dict[float, list[float]] = {}
        for ridge_lambda in self._ridge_lambdas:
            coefficients = self._fit_ridge(train_x, train_y, ridge_lambda)
            fitted_by_lambda[ridge_lambda] = coefficients
            validation_predictions = self._predict(validation_x, coefficients)
            metrics = self._metrics(validation_y, validation_predictions)
            candidates.append(
                {
                    "ridgeLambda": ridge_lambda,
                    "validation": metrics,
                }
            )

        selected = min(
            candidates,
            key=lambda item: (item["validation"]["mse"], item["ridgeLambda"]),
        )
        selected_lambda = float(selected["ridgeLambda"])
        coefficients = fitted_by_lambda[selected_lambda]
        test_predictions = self._predict(test_x, coefficients)
        test_metrics = self._metrics(test_y, test_predictions)
        zero_baseline = self._metrics(test_y, [0.0 for _ in test_y])

        return {
            "status": "shadow_linear_candidate_evaluated",
            "featureSchemaVersion": split["featureSchemaVersion"],
            "horizonDays": split.get("horizonDays"),
            "selectedFeatures": selected_features,
            "preprocessing": {
                "imputation": "train_median_only",
                "scaling": "train_mean_and_population_std_only",
                "constantFeatures": "excluded",
            },
            "selection": {
                "criterion": "minimum_validation_mse",
                "ridgeLambda": selected_lambda,
                "candidates": candidates,
            },
            "model": {
                "intercept": coefficients[0],
                "standardizedCoefficients": {
                    feature: coefficients[index + 1]
                    for index, feature in enumerate(selected_features)
                },
            },
            "test": test_metrics,
            "zeroExcessReturnBaseline": zero_baseline,
            "beatsZeroBaselineOnMse": test_metrics["mse"] < zero_baseline["mse"],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "target": "continuous_excess_return",
                "train": "fit_preprocessing_and_coefficients_only",
                "validation": "ridge_selection_only",
                "test": "final_evaluation_only_after_selection",
                "actions": "not_assigned",
                "thresholds": "not_assigned",
                "automaticModelMutation": False,
            },
            "splitCounts": split["counts"],
        }

    def _validate_frozen_split(self, split: dict[str, Any]) -> None:
        if not isinstance(split, dict):
            raise ValueError("split congelado debe ser un diccionario.")
        for key in ("train", "validation", "test", "counts", "featureSchemaVersion"):
            if key not in split:
                raise ValueError(f"split congelado sin campo obligatorio: {key}.")
        for partition in ("train", "validation", "test"):
            if not isinstance(split[partition], (list, tuple)):
                raise ValueError(f"split congelado {partition} debe ser una secuencia.")
        counts = split["counts"]
        if not isinstance(counts, dict):
            raise ValueError("split congelado counts debe ser un diccionario.")
        for partition in ("train", "validation", "test"):
            expected = counts.get(partition)
            if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
                raise ValueError(f"split congelado counts.{partition} inválido.")
            if expected != len(split[partition]):
                raise ValueError(
                    f"split congelado counts.{partition} no coincide con la partición."
                )

    def _blocked(self, split: dict[str, Any], reasons: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": "insufficient_shadow_calibration_data",
            "reasons": reasons,
            "splitCounts": split.get("counts", {}),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "actions": "not_assigned",
                "automaticModelMutation": False,
            },
        }

    def _fit_feature_schema(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[str], dict[str, float]]:
        active = []
        medians: dict[str, float] = {}
        for name in self.FEATURE_NAMES:
            values = []
            for row in rows:
                value = self._finite_float(row.get("features", {}).get(name))
                if value is not None:
                    values.append(value)
            if values:
                active.append(name)
                medians[name] = float(median(values))
        return active, medians

    def _raw_matrix(
        self,
        rows: list[dict[str, Any]],
        features: list[str],
        medians: dict[str, float],
    ) -> list[list[float]]:
        result = []
        for row in rows:
            feature_map = row.get("features", {})
            vector = []
            for feature in features:
                value = self._finite_float(feature_map.get(feature))
                vector.append(value if value is not None else medians[feature])
            result.append(vector)
        return result

    def _fit_scaler(
        self,
        matrix: list[list[float]],
    ) -> tuple[list[float], list[float], list[int]]:
        column_count = len(matrix[0])
        means = []
        scales = []
        variable_indexes = []
        for index in range(column_count):
            column = [row[index] for row in matrix]
            mean = sum(column) / len(column)
            variance = sum((value - mean) ** 2 for value in column) / len(column)
            scale = math.sqrt(variance)
            means.append(mean)
            scales.append(scale)
            if scale > 1e-12:
                variable_indexes.append(index)
        return means, scales, variable_indexes

    def _scaled_matrix(
        self,
        matrix: list[list[float]],
        means: list[float],
        scales: list[float],
        indexes: list[int],
    ) -> list[list[float]]:
        return [
            [(row[index] - means[index]) / scales[index] for index in indexes]
            for row in matrix
        ]

    def _targets(self, rows: list[dict[str, Any]]) -> list[float]:
        targets = []
        for row in rows:
            target = row.get("target", {}).get("excessReturn")
            value = self._finite_float(target)
            if value is None:
                raise ValueError("El split contiene un target excessReturn no finito.")
            targets.append(value)
        return targets

    def _fit_ridge(
        self,
        x: list[list[float]],
        y: list[float],
        ridge_lambda: float,
    ) -> list[float]:
        design = [[1.0, *row] for row in x]
        width = len(design[0])
        gram = [[0.0 for _ in range(width)] for _ in range(width)]
        rhs = [0.0 for _ in range(width)]
        for row, target in zip(design, y):
            for i in range(width):
                rhs[i] += row[i] * target
                for j in range(width):
                    gram[i][j] += row[i] * row[j]
        for index in range(1, width):
            gram[index][index] += ridge_lambda
        return self._solve_linear_system(gram, rhs)

    def _solve_linear_system(
        self,
        matrix: list[list[float]],
        rhs: list[float],
    ) -> list[float]:
        size = len(rhs)
        augmented = [matrix[i][:] + [rhs[i]] for i in range(size)]
        for column in range(size):
            pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
            if abs(augmented[pivot][column]) <= 1e-12:
                raise ValueError("La matriz de calibración es singular.")
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            pivot_value = augmented[column][column]
            for j in range(column, size + 1):
                augmented[column][j] /= pivot_value
            for row in range(size):
                if row == column:
                    continue
                factor = augmented[row][column]
                if factor == 0:
                    continue
                for j in range(column, size + 1):
                    augmented[row][j] -= factor * augmented[column][j]
        return [augmented[row][size] for row in range(size)]

    def _predict(
        self,
        x: list[list[float]],
        coefficients: list[float],
    ) -> list[float]:
        return [
            coefficients[0]
            + sum(weight * value for weight, value in zip(coefficients[1:], row))
            for row in x
        ]

    def _metrics(self, actual: list[float], predicted: list[float]) -> dict[str, float]:
        errors = [prediction - target for target, prediction in zip(actual, predicted)]
        mse = sum(error * error for error in errors) / len(errors)
        mae = sum(abs(error) for error in errors) / len(errors)
        sign_accuracy = sum(
            1
            for target, prediction in zip(actual, predicted)
            if (target >= 0) == (prediction >= 0)
        ) / len(actual)
        return {"mse": mse, "mae": mae, "signAccuracy": sign_accuracy}

    def _finite_float(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
