from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)
from app.services.recommendation_shadow_linear_candidate_service import (
    RecommendationShadowLinearCandidateService,
)


class RecommendationShadowIndependentHoldoutService:
    """Freeze a research model and evaluate only genuinely later evidence.

    Research/test folds used for model selection are not a final holdout. This
    service creates an immutable model artifact from evidence available no later
    than ``research_cutoff`` and then applies that exact artifact to observations
    strictly after the cutoff. Holdout data can never refit preprocessing,
    coefficients, feature selection or regularization.
    """

    ARTIFACT_VERSION = "shadow-frozen-linear-v1"

    def __init__(
        self,
        *,
        dataset_service: RecommendationShadowCalibrationDatasetService | None = None,
        minimum_research_rows: int = 30,
        minimum_holdout_rows: int = 10,
    ) -> None:
        if minimum_research_rows <= 0 or minimum_holdout_rows <= 0:
            raise ValueError("Los mínimos de filas deben ser positivos.")
        self._dataset_service = dataset_service or RecommendationShadowCalibrationDatasetService()
        self._minimum_research_rows = int(minimum_research_rows)
        self._minimum_holdout_rows = int(minimum_holdout_rows)

    def freeze(
        self,
        *,
        research_cutoff: datetime,
        horizon_days: int,
        ridge_lambda: float,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(research_cutoff, "research_cutoff")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")
        if ridge_lambda < 0 or not math.isfinite(float(ridge_lambda)):
            raise ValueError("ridge_lambda debe ser finito y no negativo.")

        dataset = self._dataset_service.build(
            as_of=cutoff,
            horizon_days=int(horizon_days),
            require_benchmark=True,
        )
        rows = [
            row
            for row in dataset.get("rows", [])
            if self._parse_utc(row.get("dataCutoffAt"), "dataCutoffAt") <= cutoff
            and self._parse_utc(row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt") <= cutoff
        ]
        if len(rows) < self._minimum_research_rows:
            return self._blocked(
                "insufficient_research_data",
                row_count=len(rows),
                minimum=self._minimum_research_rows,
            )

        feature_names, medians = self._fit_feature_schema(rows)
        if not feature_names:
            return self._blocked("no_finite_research_features", row_count=len(rows))
        raw = self._raw_matrix(rows, feature_names, medians)
        means, scales, variable_indexes = self._fit_scaler(raw)
        if not variable_indexes:
            return self._blocked("all_research_features_constant", row_count=len(rows))

        selected_features = [feature_names[index] for index in variable_indexes]
        selected_medians = {name: medians[name] for name in selected_features}
        selected_means = [means[index] for index in variable_indexes]
        selected_scales = [scales[index] for index in variable_indexes]
        x = [
            [
                (row[index] - means[index]) / scales[index]
                for index in variable_indexes
            ]
            for row in raw
        ]
        y = self._targets(rows)
        coefficients = self._fit_ridge(x, y, float(ridge_lambda))

        artifact_core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "featureSchemaVersion": dataset.get("featureSchemaVersion"),
            "researchCutoff": cutoff.isoformat(),
            "horizonDays": int(horizon_days),
            "ridgeLambda": float(ridge_lambda),
            "features": selected_features,
            "medians": selected_medians,
            "means": selected_means,
            "scales": selected_scales,
            "intercept": coefficients[0],
            "coefficients": coefficients[1:],
            "researchRowCount": len(rows),
        }
        fingerprint = self._fingerprint(artifact_core)
        return {
            "status": "shadow_model_frozen",
            **artifact_core,
            "fingerprint": fingerprint,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "artifact": "immutable_after_research_cutoff",
                "holdoutRefit": False,
                "holdoutFeatureSelection": False,
                "holdoutThresholdCalibration": False,
                "actions": "not_assigned",
                "automaticModelMutation": False,
            },
        }

    def evaluate(
        self,
        *,
        frozen_model: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        evaluation_cutoff = self._aware_utc(as_of, "as_of")
        model = self._validated_model(frozen_model)
        research_cutoff = self._parse_utc(model["researchCutoff"], "researchCutoff")
        if evaluation_cutoff <= research_cutoff:
            raise ValueError("as_of debe ser posterior al researchCutoff congelado.")

        dataset = self._dataset_service.build(
            as_of=evaluation_cutoff,
            horizon_days=int(model["horizonDays"]),
            require_benchmark=True,
        )
        rows = []
        excluded_not_independent = 0
        excluded_not_mature = 0
        for row in dataset.get("rows", []):
            feature_time = self._parse_utc(row.get("dataCutoffAt"), "dataCutoffAt")
            outcome_time = self._parse_utc(
                row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
            )
            if feature_time <= research_cutoff:
                excluded_not_independent += 1
                continue
            if outcome_time > evaluation_cutoff:
                excluded_not_mature += 1
                continue
            rows.append(row)

        if len(rows) < self._minimum_holdout_rows:
            return {
                **self._blocked(
                    "insufficient_independent_holdout_data",
                    row_count=len(rows),
                    minimum=self._minimum_holdout_rows,
                ),
                "modelFingerprint": model["fingerprint"],
                "researchCutoff": research_cutoff.isoformat(),
                "asOf": evaluation_cutoff.isoformat(),
                "excludedNotIndependentCount": excluded_not_independent,
                "excludedNotMatureCount": excluded_not_mature,
            }

        predictions = [self._predict_row(row, model) for row in rows]
        actual = self._targets(rows)
        metrics = self._metrics(actual, predictions)
        baseline = self._metrics(actual, [0.0 for _ in actual])
        improvement = (
            (baseline["mse"] - metrics["mse"]) / baseline["mse"]
            if baseline["mse"] > 0
            else 0.0
        )
        return {
            "status": "shadow_independent_holdout_evaluated",
            "modelFingerprint": model["fingerprint"],
            "researchCutoff": research_cutoff.isoformat(),
            "asOf": evaluation_cutoff.isoformat(),
            "horizonDays": int(model["horizonDays"]),
            "holdoutRowCount": len(rows),
            "excludedNotIndependentCount": excluded_not_independent,
            "excludedNotMatureCount": excluded_not_mature,
            "metrics": metrics,
            "zeroExcessReturnBaseline": baseline,
            "relativeMseImprovement": improvement,
            "beatsZeroBaselineOnMse": metrics["mse"] < baseline["mse"],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "independence": "features_strictly_after_frozen_research_cutoff",
                "maturity": "outcome_evaluated_at_not_after_as_of",
                "modelParameters": "frozen_and_fingerprint_verified",
                "refit": False,
                "selection": False,
                "thresholdCalibration": False,
                "actions": "not_assigned",
                "automaticModelMutation": False,
            },
        }

    def _validated_model(self, model: dict[str, Any]) -> dict[str, Any]:
        if model.get("status") != "shadow_model_frozen":
            raise ValueError("Se requiere un artefacto shadow_model_frozen.")
        if model.get("productionEligible") is not False:
            raise ValueError("Un artefacto shadow no puede ser productionEligible.")
        if model.get("advisoryStatus") != "no_advice":
            raise ValueError("Un artefacto shadow debe mantener no_advice.")
        fingerprint = model.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("El artefacto congelado requiere fingerprint.")
        core_keys = (
            "artifactVersion",
            "featureSchemaVersion",
            "researchCutoff",
            "horizonDays",
            "ridgeLambda",
            "features",
            "medians",
            "means",
            "scales",
            "intercept",
            "coefficients",
            "researchRowCount",
        )
        core = {key: model.get(key) for key in core_keys}
        if core["artifactVersion"] != self.ARTIFACT_VERSION:
            raise ValueError("Versión de artefacto congelado no compatible.")
        if self._fingerprint(core) != fingerprint:
            raise ValueError("El artefacto congelado fue modificado tras su creación.")
        features = core["features"]
        if not isinstance(features, list) or not features:
            raise ValueError("El artefacto no contiene features válidas.")
        if any(name not in RecommendationShadowLinearCandidateService.FEATURE_NAMES for name in features):
            raise ValueError("El artefacto contiene una feature no reconocida.")
        if not (
            len(features) == len(core["means"])
            == len(core["scales"])
            == len(core["coefficients"])
        ):
            raise ValueError("Dimensiones inconsistentes en el artefacto congelado.")
        for value in [core["intercept"], *core["means"], *core["scales"], *core["coefficients"]]:
            if not math.isfinite(float(value)):
                raise ValueError("El artefacto contiene parámetros no finitos.")
        if any(float(scale) <= 0 for scale in core["scales"]):
            raise ValueError("Las escalas congeladas deben ser positivas.")
        return model

    def _predict_row(self, row: dict[str, Any], model: dict[str, Any]) -> float:
        feature_map = row.get("features", {})
        values = []
        for index, feature in enumerate(model["features"]):
            value = self._finite_float(feature_map.get(feature))
            if value is None:
                value = float(model["medians"][feature])
            scaled = (value - float(model["means"][index])) / float(model["scales"][index])
            values.append(scaled)
        prediction = float(model["intercept"]) + sum(
            float(weight) * value
            for weight, value in zip(model["coefficients"], values)
        )
        if not math.isfinite(prediction):
            raise ValueError("La predicción holdout no es finita.")
        return prediction

    def _fit_feature_schema(self, rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, float]]:
        features: list[str] = []
        medians: dict[str, float] = {}
        for name in RecommendationShadowLinearCandidateService.FEATURE_NAMES:
            values = [
                value
                for row in rows
                if (value := self._finite_float(row.get("features", {}).get(name))) is not None
            ]
            if values:
                features.append(name)
                medians[name] = float(median(values))
        return features, medians

    def _raw_matrix(self, rows: list[dict[str, Any]], features: list[str], medians: dict[str, float]) -> list[list[float]]:
        result = []
        for row in rows:
            feature_map = row.get("features", {})
            result.append([
                value if (value := self._finite_float(feature_map.get(name))) is not None else medians[name]
                for name in features
            ])
        return result

    def _fit_scaler(self, matrix: list[list[float]]) -> tuple[list[float], list[float], list[int]]:
        means: list[float] = []
        scales: list[float] = []
        variable: list[int] = []
        for index in range(len(matrix[0])):
            column = [row[index] for row in matrix]
            mean = sum(column) / len(column)
            variance = sum((value - mean) ** 2 for value in column) / len(column)
            scale = math.sqrt(variance)
            means.append(mean)
            scales.append(scale)
            if scale > 1e-12:
                variable.append(index)
        return means, scales, variable

    def _fit_ridge(self, x: list[list[float]], y: list[float], ridge_lambda: float) -> list[float]:
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
        return self._solve(gram, rhs)

    def _solve(self, matrix: list[list[float]], rhs: list[float]) -> list[float]:
        size = len(rhs)
        augmented = [matrix[i][:] + [rhs[i]] for i in range(size)]
        for column in range(size):
            pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
            if abs(augmented[pivot][column]) <= 1e-12:
                raise ValueError("La matriz de calibración es singular.")
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            divisor = augmented[column][column]
            for j in range(column, size + 1):
                augmented[column][j] /= divisor
            for row in range(size):
                if row == column:
                    continue
                factor = augmented[row][column]
                for j in range(column, size + 1):
                    augmented[row][j] -= factor * augmented[column][j]
        return [augmented[row][size] for row in range(size)]

    def _targets(self, rows: list[dict[str, Any]]) -> list[float]:
        values = []
        for row in rows:
            value = self._finite_float(row.get("target", {}).get("excessReturn"))
            if value is None:
                raise ValueError("El dataset contiene excessReturn no finito.")
            values.append(value)
        return values

    def _metrics(self, actual: list[float], predicted: list[float]) -> dict[str, float]:
        errors = [prediction - target for target, prediction in zip(actual, predicted)]
        return {
            "mse": sum(error * error for error in errors) / len(errors),
            "mae": sum(abs(error) for error in errors) / len(errors),
            "signAccuracy": sum(
                1 for target, prediction in zip(actual, predicted)
                if (target >= 0) == (prediction >= 0)
            ) / len(actual),
        }

    def _blocked(self, reason: str, **details: Any) -> dict[str, Any]:
        return {
            "status": reason,
            **details,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {"actions": "not_assigned", "automaticModelMutation": False},
        }

    def _fingerprint(self, core: dict[str, Any]) -> str:
        payload = json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _parse_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} no contiene un timestamp ISO válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _finite_float(self, value: object) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
