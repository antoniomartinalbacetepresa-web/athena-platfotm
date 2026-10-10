from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)


class RecommendationShadowTemporalSplitService:
    """Create purged chronological train/validation/test calibration partitions.

    A row is usable in a partition only when both its feature timestamp and its
    outcome availability belong entirely before that partition's next boundary.
    This prevents labels that mature later from leaking backwards into model
    selection. Rows are never randomly shuffled.
    """

    def __init__(
        self,
        *,
        dataset_service: RecommendationShadowCalibrationDatasetService | None = None,
    ) -> None:
        self._dataset_service = (
            dataset_service
            if dataset_service is not None
            else RecommendationShadowCalibrationDatasetService()
        )

    def build(
        self,
        *,
        as_of: datetime,
        train_end: datetime,
        validation_end: datetime,
        horizon_days: int | None = None,
        require_benchmark: bool = True,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        train_boundary = self._aware_utc(train_end, "train_end")
        validation_boundary = self._aware_utc(validation_end, "validation_end")
        if not train_boundary < validation_boundary < cutoff:
            raise ValueError(
                "Se requiere train_end < validation_end < as_of para un split temporal."
            )

        dataset = self._dataset_service.build(
            as_of=cutoff,
            horizon_days=horizon_days,
            require_benchmark=require_benchmark,
        )

        train: list[dict[str, Any]] = []
        validation: list[dict[str, Any]] = []
        test: list[dict[str, Any]] = []
        purged: list[dict[str, Any]] = []

        for row in dataset["rows"]:
            feature_time = self._parse_utc(row.get("dataCutoffAt"), "dataCutoffAt")
            outcome_time = self._parse_utc(
                row.get("outcomeEvaluatedAt"),
                "outcomeEvaluatedAt",
            )

            if feature_time < train_boundary:
                if outcome_time <= train_boundary:
                    train.append(row)
                else:
                    purged.append(self._purged_row(row, "train_label_not_known_at_boundary"))
                continue

            if feature_time < validation_boundary:
                if outcome_time <= validation_boundary:
                    validation.append(row)
                else:
                    purged.append(
                        self._purged_row(row, "validation_label_not_known_at_boundary")
                    )
                continue

            if feature_time <= cutoff:
                if outcome_time <= cutoff:
                    test.append(row)
                else:
                    purged.append(self._purged_row(row, "test_label_not_known_at_as_of"))

        return {
            "status": "shadow_calibration_temporal_split",
            "asOf": cutoff.isoformat(),
            "featureSchemaVersion": dataset["featureSchemaVersion"],
            "horizonDays": horizon_days,
            "requireBenchmark": require_benchmark,
            "boundaries": {
                "trainEnd": train_boundary.isoformat(),
                "validationEnd": validation_boundary.isoformat(),
                "testEnd": cutoff.isoformat(),
            },
            "counts": {
                "source": dataset["rowCount"],
                "train": len(train),
                "validation": len(validation),
                "test": len(test),
                "purged": len(purged),
            },
            "train": train,
            "validation": validation,
            "test": test,
            "purged": purged,
            "advisoryStatus": "no_advice",
            "policy": {
                "split": "strict_chronological_no_shuffle",
                "purging": "label_must_be_known_by_next_partition_boundary",
                "modelSelection": "train_then_validation_only",
                "finalEvaluation": "test_partition_must_remain_untouched",
                "actions": "not_assigned",
                "productionEligibility": False,
            },
        }

    def _purged_row(self, row: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "snapshotId": row.get("snapshotId"),
            "symbol": row.get("symbol"),
            "horizonDays": row.get("horizonDays"),
            "dataCutoffAt": row.get("dataCutoffAt"),
            "outcomeEvaluatedAt": row.get("outcomeEvaluatedAt"),
            "reason": reason,
        }

    def _parse_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} es obligatorio para el split temporal.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} no contiene un timestamp ISO válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
