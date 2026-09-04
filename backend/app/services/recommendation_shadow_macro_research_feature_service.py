from __future__ import annotations

import copy
import math
from typing import Any


class RecommendationShadowMacroResearchFeatureService:
    """Derive deterministic macro research features from frozen OOS evidence.

    This stage deliberately performs no cross-row fitting, normalization,
    direction assignment, thresholding, weighting, or candidate scoring. Each
    feature is only the raw finite value that was frozen in the corresponding
    shadow snapshot, with its full PIT/provenance metadata preserved.

    A feature identity is metric + entity + unit. Exact duplicate observations
    are deduplicated deterministically. Conflicting observations for the same
    identity reject the row fail-closed instead of choosing a source/value by
    intuition.
    """

    DATASET_SCHEMA_VERSION = "shadow-macro-research-v1"

    def build(self, *, calibration_dataset: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(calibration_dataset, dict):
            raise ValueError("calibration_dataset debe ser un objeto.")
        if calibration_dataset.get("status") != "shadow_calibration_dataset":
            raise ValueError("calibration_dataset no tiene el contrato esperado.")
        if calibration_dataset.get("advisoryStatus") != "no_advice":
            raise ValueError("El dataset de investigacion debe mantener no_advice.")

        raw_rows = calibration_dataset.get("rows")
        if not isinstance(raw_rows, list):
            raise ValueError("calibration_dataset.rows debe ser una lista.")

        accepted: list[dict[str, Any]] = []
        rejected_invalid_macro = 0
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                rejected_invalid_macro += 1
                continue

            macro_observations = raw_row.get("macroObservations")
            if macro_observations is None:
                macro_observations = []
            if not isinstance(macro_observations, list):
                rejected_invalid_macro += 1
                continue

            features, valid = self._features_from_observations(macro_observations)
            if not valid:
                rejected_invalid_macro += 1
                continue

            row = copy.deepcopy(raw_row)
            row["macroResearchFeatures"] = features
            accepted.append(row)

        return {
            "status": "shadow_macro_research_dataset",
            "datasetSchemaVersion": self.DATASET_SCHEMA_VERSION,
            "sourceFeatureSchemaVersion": calibration_dataset.get(
                "featureSchemaVersion"
            ),
            "asOf": calibration_dataset.get("asOf"),
            "horizonDays": calibration_dataset.get("horizonDays"),
            "requireBenchmark": calibration_dataset.get("requireBenchmark"),
            "rowCount": len(accepted),
            "rejectedInvalidMacroCount": rejected_invalid_macro,
            "rows": accepted,
            "advisoryStatus": "no_advice",
            "policy": {
                "macroFeatures": "raw_frozen_values_with_pit_provenance",
                "normalization": "not_fit_in_this_stage",
                "direction": "not_assigned",
                "featureWeights": "not_assigned",
                "thresholds": "not_assigned",
                "candidateInfluence": "disabled",
                "duplicates": "exact_dedupe_conflicts_rejected",
                "trainingUse": "fit_only_inside_training_folds_then_validate_oos",
            },
        }

    def _features_from_observations(
        self,
        observations: list[object],
    ) -> tuple[list[dict[str, Any]], bool]:
        by_key: dict[str, dict[str, Any]] = {}
        for raw in observations:
            if not isinstance(raw, dict):
                return [], False

            metric = str(raw.get("metric") or "").strip()
            entity = str(raw.get("entity") or "").strip()
            unit = str(raw.get("unit") or "").strip()
            source = str(raw.get("source") or "").strip()
            observed_at = str(raw.get("observedAt") or "").strip()
            available_at = str(raw.get("availableAt") or "").strip()
            retrieved_at = str(raw.get("retrievedAt") or "").strip()
            source_url = str(raw.get("sourceUrl") or "").strip()
            value = self._finite_float(raw.get("value"))
            quality_score = self._optional_bounded_score(raw.get("qualityScore"))
            confidence = self._optional_bounded_score(raw.get("confidence"))

            if (
                not metric.startswith("macro.")
                or not entity
                or not unit
                or not source
                or not observed_at
                or not available_at
                or not retrieved_at
                or not source_url
                or value is None
            ):
                return [], False
            if raw.get("qualityScore") is not None and quality_score is None:
                return [], False
            if raw.get("confidence") is not None and confidence is None:
                return [], False

            key = f"{metric}|{entity}|{unit}"
            feature = {
                "key": key,
                "metric": metric,
                "entity": entity,
                "unit": unit,
                "value": value,
                "source": source,
                "observedAt": observed_at,
                "availableAt": available_at,
                "retrievedAt": retrieved_at,
                "sourceUrl": source_url,
                "qualityScore": quality_score,
                "confidence": confidence,
                "transformation": "raw_frozen_value",
            }

            previous = by_key.get(key)
            if previous is None:
                by_key[key] = feature
            elif previous != feature:
                return [], False

        return [by_key[key] for key in sorted(by_key)], True

    def _finite_float(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _optional_bounded_score(self, value: object) -> float | None:
        if value is None:
            return None
        parsed = self._finite_float(value)
        if parsed is None or parsed < 0.0 or parsed > 100.0:
            return None
        return parsed
