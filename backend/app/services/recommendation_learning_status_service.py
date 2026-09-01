from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_calibration_service import (
    RecommendationCalibrationService,
)
from app.services.recommendation_drift_service import RecommendationDriftService
from app.services.recommendation_evaluation_schedule_service import (
    RecommendationEvaluationScheduleService,
)
from app.services.recommendation_performance_service import (
    RecommendationPerformanceService,
)


class RecommendationLearningStatusService:
    """Builds one auditable status for ATHENA recommendation learning."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def get_status(
        self,
        *,
        as_of: datetime,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> dict[str, Any]:
        performance = RecommendationPerformanceService(
            database=self._database
        ).get_report(
            model_version=model_version,
            horizon_days=horizon_days,
        )
        calibration = RecommendationCalibrationService(
            database=self._database
        ).get_report(
            model_version=model_version,
            horizon_days=horizon_days,
        )
        schedule = RecommendationEvaluationScheduleService(
            database=self._database
        ).get_report(as_of=as_of)

        drift: dict[str, Any] | None = None
        if model_version is not None and horizon_days is not None:
            drift = RecommendationDriftService(
                database=self._database
            ).get_report(
                model_version=model_version,
                horizon_days=horizon_days,
                as_of=as_of,
            ).to_api_dict()

        return {
            "status": "learning_diagnostics_only",
            "asOf": schedule.as_of,
            "filters": {
                "modelVersion": model_version,
                "horizonDays": horizon_days,
            },
            "performance": performance.to_api_dict(),
            "calibration": calibration.to_api_dict(),
            "evaluationSchedule": schedule.to_api_dict(),
            "drift": drift,
            "automaticModelMutation": False,
        }
