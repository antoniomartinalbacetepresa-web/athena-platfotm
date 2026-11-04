from __future__ import annotations

import math
from statistics import median
from typing import Any


class RecommendationShadowMacroFoldPreprocessingService:
    """Fit macro preprocessing on one walk-forward training fold only.

    The service consumes already frozen ``macroResearchFeatures``. Feature
    discovery, imputation and scaling parameters are learned exclusively from
    the training partition. Validation/test rows can only be transformed with
    those frozen train parameters; they cannot create features or change any
    fitted statistic.

    This is research infrastructure only. It does not inspect targets, assign
    direction/weights/actions, mutate ATHENA scores, or make a candidate
    production eligible.
    """

    SCHEMA_VERSION = "shadow-macro-fold-preprocessing-v1"

    def fit_transform(
        self,
        *,
        train_rows: list[dict[str, Any]],
        validation_rows: list[dict[str, Any]],
        test_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not train_rows:
            return self._blocked("empty_train_partition")

        train_maps = [self._feature_map(row, partition="train") for row in train_rows]
        validation_maps = [
            self._feature_map(row, partition="validation") for row in validation_rows
        ]
        test_maps = [self._feature_map(row, partition="test") for row in test_rows]

        train_feature_keys = sorted({key for row in train_maps for key in row})
        if not train_feature_keys:
            return self._blocked("no_train_macro_features")

        medians: dict[str, float] = {}
        for key in train_feature_keys:
            values = [row[key] for row in train_maps if key in row]
            if not values:
                continue
            medians[key] = float(median(values))

        raw_train = self._raw_matrix(train_maps, train_feature_keys, medians)
        means, scales, variable_indexes = self._fit_scaler(raw_train)
        if not variable_indexes:
            return self._blocked("all_train_macro_features_constant")

        selected_keys = [train_feature_keys[index] for index in variable_indexes]
        fit_parameters = {
            key: {
                "median": medians[key],
                "mean": means[index],
                "populationStd": scales[index],
            }
            for index, key in enumerate(train_feature_keys)
            if index in variable_indexes
        }

        return {
            "status": "shadow_macro_fold_preprocessing_fitted",
            "schemaVersion": self.SCHEMA_VERSION,
            "selectedFeatures": selected_keys,
            "fitParameters": fit_parameters,
            "partitions": {
                "train": self._transform(
                    train_rows,
                    train_maps,
                    train_feature_keys,
                    medians,
                    means,
                    scales,
                    variable_indexes,
                ),
                "validation": self._transform(
                    validation_rows,
                    validation_maps,
                    train_feature_keys,
                    medians,
                    means,
                    scales,
                    variable_indexes,
                ),
                "test": self._transform(
                    test_rows,
                    test_maps,
                    train_feature_keys,
                    medians,
                    means,
                    scales,
                    variable_indexes,
                ),
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "featureDiscovery": "train_only",
                "imputation": "train_median_only",
                "scaling": "train_mean_and_population_std_only",
                "validationAndTest": "transform_only_with_frozen_train_parameters",
                "unknownValidationOrTestFeatures": "ignored",
                "targets": "not_read",
                "direction": "not_assigned",
                "featureWeights": "not_assigned",
                "actions": "not_assigned",
                "candidateInfluence": "disabled",
                "automaticModelMutation": False,
            },
        }

    def _feature_map(
        self,
        row: dict[str, Any],
        *,
        partition: str,
    ) -> dict[str, float]:
        if not isinstance(row, dict):
            raise ValueError(f"{partition} contiene una fila no valida.")
        raw_features = row.get("macroResearchFeatures")
        if raw_features is None:
            raw_features = []
        if not isinstance(raw_features, list):
            raise ValueError(f"{partition}.macroResearchFeatures debe ser una lista.")

        result: dict[str, float] = {}
        for feature in raw_features:
            if not isinstance(feature, dict):
                raise ValueError(f"{partition} contiene una macro feature no valida.")
            key = str(feature.get("key") or "").strip()
            if not key:
                raise ValueError(f"{partition} contiene una macro feature sin key.")
            value = self._finite_float(feature.get("value"))
            if value is None:
                raise ValueError(f"{partition} contiene una macro feature no finita.")
            previous = result.get(key)
            if previous is not None and previous != value:
                raise ValueError(
                    f"{partition} contiene macro features conflictivas para {key}."
                )
            result[key] = value
        return result

    def _raw_matrix(
        self,
        maps: list[dict[str, float]],
        feature_keys: list[str],
        medians: dict[str, float],
    ) -> list[list[float]]:
        return [
            [feature_map.get(key, medians[key]) for key in feature_keys]
            for feature_map in maps
        ]

    def _fit_scaler(
        self,
        matrix: list[list[float]],
    ) -> tuple[list[float], list[float], list[int]]:
        means: list[float] = []
        scales: list[float] = []
        variable_indexes: list[int] = []
        for index in range(len(matrix[0])):
            column = [row[index] for row in matrix]
            mean = sum(column) / len(column)
            variance = sum((value - mean) ** 2 for value in column) / len(column)
            scale = math.sqrt(variance)
            means.append(mean)
            scales.append(scale)
            if scale > 1e-12:
                variable_indexes.append(index)
        return means, scales, variable_indexes

    def _transform(
        self,
        rows: list[dict[str, Any]],
        maps: list[dict[str, float]],
        feature_keys: list[str],
        medians: dict[str, float],
        means: list[float],
        scales: list[float],
        variable_indexes: list[int],
    ) -> list[dict[str, Any]]:
        raw = self._raw_matrix(maps, feature_keys, medians)
        result: list[dict[str, Any]] = []
        for row, vector in zip(rows, raw):
            values = {
                feature_keys[index]: (vector[index] - means[index]) / scales[index]
                for index in variable_indexes
            }
            if any(not math.isfinite(value) for value in values.values()):
                raise ValueError("La transformacion macro produjo un valor no finito.")
            result.append(
                {
                    "snapshotId": row.get("snapshotId"),
                    "dataCutoffAt": row.get("dataCutoffAt"),
                    "values": values,
                }
            )
        return result

    def _blocked(self, reason: str) -> dict[str, Any]:
        return {
            "status": "insufficient_macro_fold_preprocessing_data",
            "schemaVersion": self.SCHEMA_VERSION,
            "reason": reason,
            "selectedFeatures": [],
            "fitParameters": {},
            "partitions": {"train": [], "validation": [], "test": []},
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "featureDiscovery": "train_only",
                "candidateInfluence": "disabled",
                "actions": "not_assigned",
                "automaticModelMutation": False,
            },
        }

    def _finite_float(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
