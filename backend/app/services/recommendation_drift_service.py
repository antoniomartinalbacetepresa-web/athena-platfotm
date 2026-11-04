from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)


@dataclass(frozen=True)
class RecommendationDriftWindow:
    sample_count: int
    directional_accuracy: float | None
    average_excess_return: float | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "sampleCount": self.sample_count,
            "directionalAccuracy": self.directional_accuracy,
            "averageExcessReturn": self.average_excess_return,
        }


@dataclass(frozen=True)
class RecommendationDriftReport:
    status: str
    model_version: str
    horizon_days: int
    as_of: str
    recent_window_days: int
    baseline_window_days: int
    minimum_sample_size: int
    accuracy_drop_threshold: float
    excess_return_drop_threshold: float
    baseline: RecommendationDriftWindow
    recent: RecommendationDriftWindow
    accuracy_delta: float | None
    excess_return_delta: float | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "modelVersion": self.model_version,
            "horizonDays": self.horizon_days,
            "asOf": self.as_of,
            "recentWindowDays": self.recent_window_days,
            "baselineWindowDays": self.baseline_window_days,
            "minimumSampleSize": self.minimum_sample_size,
            "accuracyDropThreshold": self.accuracy_drop_threshold,
            "excessReturnDropThreshold": self.excess_return_drop_threshold,
            "baseline": self.baseline.to_api_dict(),
            "recent": self.recent.to_api_dict(),
            "accuracyDelta": self.accuracy_delta,
            "excessReturnDelta": self.excess_return_delta,
            "autoAction": False,
            "warning": (
                "La degradación detectada requiere revisión. Este diagnóstico no "
                "desactiva ni modifica automáticamente el modelo."
            ),
        }


class RecommendationDriftService:
    _DIRECTIONAL_ACTIONS = frozenset({"buy", "reduce", "sell"})

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        recent_window_days: int = 90,
        baseline_window_days: int = 365,
        minimum_sample_size: int = 20,
        accuracy_drop_threshold: float = 0.10,
        excess_return_drop_threshold: float = 0.02,
    ) -> None:
        if recent_window_days <= 0 or baseline_window_days <= 0:
            raise ValueError("Las ventanas deben ser mayores que 0.")
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size debe ser mayor que 0.")
        if not 0 < accuracy_drop_threshold <= 1:
            raise ValueError("accuracy_drop_threshold debe estar entre 0 y 1.")
        if excess_return_drop_threshold <= 0:
            raise ValueError("excess_return_drop_threshold debe ser mayor que 0.")

        self._database = database if database is not None else AthenaDatabase()
        self._history = RecommendationHistoryRepository(database=self._database)
        self._recent_window_days = int(recent_window_days)
        self._baseline_window_days = int(baseline_window_days)
        self._minimum_sample_size = int(minimum_sample_size)
        self._accuracy_drop_threshold = float(accuracy_drop_threshold)
        self._excess_return_drop_threshold = float(excess_return_drop_threshold)

    def get_report(
        self,
        *,
        model_version: str,
        horizon_days: int,
        as_of: datetime,
    ) -> RecommendationDriftReport:
        self._history.initialize()
        version = str(model_version or "").strip()
        if not version:
            raise ValueError("model_version es obligatorio.")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser mayor que 0.")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")

        as_of_utc = as_of.astimezone(timezone.utc)
        recent_start = as_of_utc - timedelta(days=self._recent_window_days)
        baseline_start = recent_start - timedelta(days=self._baseline_window_days)

        observations = self._load_observations(
            model_version=version,
            horizon_days=int(horizon_days),
            baseline_start=baseline_start,
            as_of=as_of_utc,
        )

        baseline_rows = [
            row
            for row in observations
            if baseline_start <= row["generated_at"] < recent_start
        ]
        recent_rows = [
            row
            for row in observations
            if recent_start <= row["generated_at"] <= as_of_utc
        ]

        baseline = self._summarize(baseline_rows)
        recent = self._summarize(recent_rows)

        if (
            baseline.sample_count < self._minimum_sample_size
            or recent.sample_count < self._minimum_sample_size
            or baseline.directional_accuracy is None
            or recent.directional_accuracy is None
        ):
            status = "insufficient_sample"
            accuracy_delta = None
            excess_delta = None
        else:
            accuracy_delta = (
                recent.directional_accuracy - baseline.directional_accuracy
            )
            excess_delta = self._optional_delta(
                recent.average_excess_return,
                baseline.average_excess_return,
            )
            accuracy_degraded = accuracy_delta <= -self._accuracy_drop_threshold
            excess_degraded = (
                excess_delta is not None
                and excess_delta <= -self._excess_return_drop_threshold
            )
            if accuracy_degraded and excess_degraded:
                status = "degraded"
            elif accuracy_degraded or excess_degraded:
                status = "watch"
            else:
                status = "stable"

        return RecommendationDriftReport(
            status=status,
            model_version=version,
            horizon_days=int(horizon_days),
            as_of=as_of_utc.isoformat(),
            recent_window_days=self._recent_window_days,
            baseline_window_days=self._baseline_window_days,
            minimum_sample_size=self._minimum_sample_size,
            accuracy_drop_threshold=self._accuracy_drop_threshold,
            excess_return_drop_threshold=self._excess_return_drop_threshold,
            baseline=baseline,
            recent=recent,
            accuracy_delta=accuracy_delta,
            excess_return_delta=excess_delta,
        )

    def _load_observations(
        self,
        *,
        model_version: str,
        horizon_days: int,
        baseline_start: datetime,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    r.action,
                    r.generated_at,
                    o.realized_return,
                    o.excess_return
                FROM athena_recommendation_outcomes o
                JOIN athena_recommendations r ON r.id = o.recommendation_id
                WHERE r.model_version = ?
                  AND o.horizon_days = ?
                  AND r.generated_at >= ?
                  AND r.generated_at <= ?
                  AND r.action IN ('buy', 'reduce', 'sell')
                ORDER BY r.generated_at
                """,
                (
                    model_version,
                    horizon_days,
                    baseline_start.isoformat(),
                    as_of.isoformat(),
                ),
            ).fetchall()

        observations: list[dict[str, Any]] = []
        for row in rows:
            generated = datetime.fromisoformat(str(row["generated_at"]))
            if generated.tzinfo is None or generated.utcoffset() is None:
                raise RuntimeError(
                    "Se encontró una recomendación histórica sin zona horaria."
                )
            observations.append(
                {
                    "action": str(row["action"]),
                    "generated_at": generated.astimezone(timezone.utc),
                    "realized_return": float(row["realized_return"]),
                    "excess_return": (
                        float(row["excess_return"])
                        if row["excess_return"] is not None
                        else None
                    ),
                }
            )
        return observations

    def _summarize(self, rows: list[dict[str, Any]]) -> RecommendationDriftWindow:
        successes = sum(1 for row in rows if self._is_success(row))
        excess = [
            float(row["excess_return"])
            for row in rows
            if row["excess_return"] is not None
        ]
        return RecommendationDriftWindow(
            sample_count=len(rows),
            directional_accuracy=(successes / len(rows) if rows else None),
            average_excess_return=(mean(excess) if excess else None),
        )

    def _is_success(self, row: dict[str, Any]) -> bool:
        action = str(row["action"])
        realized = float(row["realized_return"])
        if action == "buy":
            return realized > 0
        if action in {"reduce", "sell"}:
            return realized < 0
        raise ValueError(f"Acción no direccional inesperada: {action}")

    def _optional_delta(
        self,
        recent: float | None,
        baseline: float | None,
    ) -> float | None:
        if recent is None or baseline is None:
            return None
        return recent - baseline
