from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_performance_service import (
    RecommendationPerformanceService,
)


@dataclass(frozen=True)
class RecommendationCalibrationProposal:
    label: str
    sample_count: int
    average_conviction: float | None
    observed_accuracy: float | None
    calibration_gap: float | None
    proposed_delta: float | None
    status: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "sampleCount": self.sample_count,
            "averageConviction": self.average_conviction,
            "observedAccuracy": self.observed_accuracy,
            "calibrationGap": self.calibration_gap,
            "proposedDelta": self.proposed_delta,
            "status": self.status,
        }


@dataclass(frozen=True)
class RecommendationCalibrationReport:
    model_version: str | None
    horizon_days: int | None
    minimum_sample_size: int
    learning_rate: float
    maximum_step: float
    proposals: tuple[RecommendationCalibrationProposal, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "proposal_only",
            "modelVersion": self.model_version,
            "horizonDays": self.horizon_days,
            "minimumSampleSize": self.minimum_sample_size,
            "learningRate": self.learning_rate,
            "maximumStep": self.maximum_step,
            "proposals": [proposal.to_api_dict() for proposal in self.proposals],
            "autoApply": False,
            "warning": (
                "Los ajustes son propuestas auditables. ATHENA no modifica pesos, "
                "umbrales ni modelos automáticamente a partir de este informe."
            ),
        }


class RecommendationCalibrationService:
    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        minimum_sample_size: int = 20,
        learning_rate: float = 0.25,
        maximum_step: float = 0.05,
    ) -> None:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size debe ser mayor que 0.")
        if not 0 < learning_rate <= 1:
            raise ValueError("learning_rate debe estar entre 0 y 1.")
        if not 0 < maximum_step <= 0.25:
            raise ValueError("maximum_step debe estar entre 0 y 0.25.")

        self._database = database if database is not None else AthenaDatabase()
        self._minimum_sample_size = int(minimum_sample_size)
        self._learning_rate = float(learning_rate)
        self._maximum_step = float(maximum_step)

    def get_report(
        self,
        *,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> RecommendationCalibrationReport:
        performance = RecommendationPerformanceService(
            database=self._database
        ).get_report(
            model_version=model_version,
            horizon_days=horizon_days,
        )

        proposals: list[RecommendationCalibrationProposal] = []
        for bucket in performance.conviction_buckets:
            sample_count = int(bucket["sampleCount"])
            average_conviction = bucket["averageConviction"]
            observed_accuracy = bucket["directionalAccuracy"]

            if (
                sample_count < self._minimum_sample_size
                or average_conviction is None
                or observed_accuracy is None
            ):
                proposals.append(
                    RecommendationCalibrationProposal(
                        label=str(bucket["label"]),
                        sample_count=sample_count,
                        average_conviction=(
                            float(average_conviction)
                            if average_conviction is not None
                            else None
                        ),
                        observed_accuracy=(
                            float(observed_accuracy)
                            if observed_accuracy is not None
                            else None
                        ),
                        calibration_gap=None,
                        proposed_delta=None,
                        status="insufficient_sample",
                    )
                )
                continue

            gap = float(observed_accuracy) - float(average_conviction)
            raw_delta = gap * self._learning_rate
            proposed_delta = max(
                -self._maximum_step,
                min(self._maximum_step, raw_delta),
            )
            proposals.append(
                RecommendationCalibrationProposal(
                    label=str(bucket["label"]),
                    sample_count=sample_count,
                    average_conviction=float(average_conviction),
                    observed_accuracy=float(observed_accuracy),
                    calibration_gap=gap,
                    proposed_delta=proposed_delta,
                    status="review_required",
                )
            )

        return RecommendationCalibrationReport(
            model_version=model_version,
            horizon_days=horizon_days,
            minimum_sample_size=self._minimum_sample_size,
            learning_rate=self._learning_rate,
            maximum_step=self._maximum_step,
            proposals=tuple(proposals),
        )
