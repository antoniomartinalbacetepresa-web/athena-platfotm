from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)
from app.services.recommendation_shadow_temporal_split_service import (
    RecommendationShadowTemporalSplitService,
)


class RecommendationShadowWalkForwardPlanService:
    """Build expanding walk-forward folds from real PIT calibration timestamps.

    Boundaries are derived only from feature timestamps. Outcome values never
    influence where a fold is placed. Each proposed fold is then checked with
    the same purged temporal split used by candidate evaluation, so labels that
    were not actually known by a boundary cannot make a fold look sufficiently
    populated.

    This is research infrastructure only. It does not select an investment
    action, promote a model, or mutate any production configuration.
    """

    def __init__(
        self,
        *,
        dataset_service: RecommendationShadowCalibrationDatasetService | None = None,
        split_service: RecommendationShadowTemporalSplitService | None = None,
        minimum_train_rows: int = 30,
        minimum_validation_rows: int = 10,
        minimum_test_rows: int = 10,
        step_rows: int = 10,
        maximum_folds: int = 12,
    ) -> None:
        values = (
            minimum_train_rows,
            minimum_validation_rows,
            minimum_test_rows,
            step_rows,
            maximum_folds,
        )
        if min(values) <= 0:
            raise ValueError("Los mínimos, step_rows y maximum_folds deben ser positivos.")
        self._dataset_service = (
            dataset_service
            if dataset_service is not None
            else RecommendationShadowCalibrationDatasetService()
        )
        self._split_service = (
            split_service
            if split_service is not None
            else RecommendationShadowTemporalSplitService()
        )
        self._minimum_train_rows = int(minimum_train_rows)
        self._minimum_validation_rows = int(minimum_validation_rows)
        self._minimum_test_rows = int(minimum_test_rows)
        self._step_rows = int(step_rows)
        self._maximum_folds = int(maximum_folds)

    def build(
        self,
        *,
        as_of: datetime,
        horizon_days: int,
        require_benchmark: bool = True,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")

        dataset = self._dataset_service.build(
            as_of=cutoff,
            horizon_days=horizon_days,
            require_benchmark=require_benchmark,
        )
        grouped = self._group_feature_times(dataset.get("rows", []), cutoff)
        proposals = self._propose_boundaries(grouped)

        ready_folds: list[dict[str, datetime]] = []
        diagnostics: list[dict[str, Any]] = []
        for proposal_index, proposal in enumerate(proposals):
            split = self._split_service.build(
                as_of=proposal["as_of"],
                train_end=proposal["train_end"],
                validation_end=proposal["validation_end"],
                horizon_days=horizon_days,
                require_benchmark=require_benchmark,
            )
            counts = split.get("counts", {})
            deficiencies = self._deficiencies(counts)
            accepted = not deficiencies
            if accepted:
                ready_folds.append(proposal)
            diagnostics.append(
                {
                    "proposalIndex": proposal_index,
                    "boundaries": self._serialized_boundaries(proposal),
                    "counts": {
                        "train": int(counts.get("train", 0)),
                        "validation": int(counts.get("validation", 0)),
                        "test": int(counts.get("test", 0)),
                        "purged": int(counts.get("purged", 0)),
                    },
                    "accepted": accepted,
                    "deficiencies": deficiencies,
                }
            )

        return {
            "status": (
                "shadow_walk_forward_plan_ready"
                if ready_folds
                else "insufficient_shadow_walk_forward_plan_data"
            ),
            "asOf": cutoff.isoformat(),
            "horizonDays": horizon_days,
            "sourceRowCount": int(dataset.get("rowCount", len(dataset.get("rows", [])))),
            "uniqueFeatureTimeCount": len(grouped),
            "proposalCount": len(proposals),
            "readyFoldCount": len(ready_folds),
            "folds": ready_folds,
            "diagnostics": diagnostics,
            "requirements": {
                "minimumTrainRows": self._minimum_train_rows,
                "minimumValidationRows": self._minimum_validation_rows,
                "minimumTestRows": self._minimum_test_rows,
                "stepRows": self._step_rows,
                "maximumFolds": self._maximum_folds,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "boundarySelection": "feature_timestamps_only",
                "purging": "validated_with_temporal_split_service",
                "outcomeValuesUsedForBoundarySelection": False,
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "productionEligibility": False,
            },
        }

    def _group_feature_times(
        self,
        rows: list[dict[str, Any]],
        cutoff: datetime,
    ) -> list[tuple[datetime, int]]:
        counts: dict[datetime, int] = {}
        for row in rows:
            value = row.get("dataCutoffAt")
            parsed = self._parse_utc(value, "dataCutoffAt")
            if parsed > cutoff:
                raise ValueError("El dataset contiene dataCutoffAt posterior a as_of.")
            counts[parsed] = counts.get(parsed, 0) + 1
        return sorted(counts.items(), key=lambda item: item[0])

    def _propose_boundaries(
        self,
        grouped: list[tuple[datetime, int]],
    ) -> list[dict[str, datetime]]:
        if len(grouped) < 3:
            return []

        proposals: list[dict[str, datetime]] = []
        train_index = self._first_boundary_index(grouped, 0, self._minimum_train_rows)
        while train_index is not None and len(proposals) < self._maximum_folds:
            validation_index = self._first_boundary_index(
                grouped,
                train_index,
                self._minimum_validation_rows,
            )
            if validation_index is None:
                break
            test_index = self._first_test_end_index(
                grouped,
                validation_index,
                self._minimum_test_rows,
            )
            if test_index is None:
                break

            train_end = grouped[train_index][0]
            validation_end = grouped[validation_index][0]
            test_end = grouped[test_index][0]
            if train_end < validation_end < test_end:
                proposals.append(
                    {
                        "train_end": train_end,
                        "validation_end": validation_end,
                        "as_of": test_end,
                    }
                )

            next_train_index = self._first_boundary_index(
                grouped,
                train_index,
                self._step_rows,
            )
            if next_train_index is None or next_train_index <= train_index:
                break
            train_index = next_train_index

        return proposals

    def _first_boundary_index(
        self,
        grouped: list[tuple[datetime, int]],
        start_index: int,
        minimum_rows_before_boundary: int,
    ) -> int | None:
        accumulated = 0
        for index in range(start_index, len(grouped)):
            if accumulated >= minimum_rows_before_boundary:
                return index
            accumulated += grouped[index][1]
        return None

    def _first_test_end_index(
        self,
        grouped: list[tuple[datetime, int]],
        start_index: int,
        minimum_rows_through_end: int,
    ) -> int | None:
        accumulated = 0
        for index in range(start_index, len(grouped)):
            accumulated += grouped[index][1]
            if accumulated >= minimum_rows_through_end:
                return index
        return None

    def _deficiencies(self, counts: dict[str, Any]) -> list[dict[str, int | str]]:
        result: list[dict[str, int | str]] = []
        for partition, minimum in (
            ("train", self._minimum_train_rows),
            ("validation", self._minimum_validation_rows),
            ("test", self._minimum_test_rows),
        ):
            actual = int(counts.get(partition, 0))
            if actual < minimum:
                result.append(
                    {
                        "partition": partition,
                        "rowCount": actual,
                        "minimum": minimum,
                    }
                )
        return result

    def _serialized_boundaries(self, fold: dict[str, datetime]) -> dict[str, str]:
        return {
            "trainEnd": fold["train_end"].isoformat(),
            "validationEnd": fold["validation_end"].isoformat(),
            "testEnd": fold["as_of"].isoformat(),
        }

    def _parse_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} es obligatorio para planificar walk-forward.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} no contiene un timestamp ISO válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
