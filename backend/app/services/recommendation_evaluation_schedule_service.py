from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)


@dataclass(frozen=True)
class DueRecommendationEvaluation:
    recommendation_id: int
    symbol: str
    model_version: str
    action: str
    generated_at: str
    horizon_days: int
    due_at: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "recommendationId": self.recommendation_id,
            "symbol": self.symbol,
            "modelVersion": self.model_version,
            "action": self.action,
            "generatedAt": self.generated_at,
            "horizonDays": self.horizon_days,
            "dueAt": self.due_at,
        }


@dataclass(frozen=True)
class RecommendationEvaluationScheduleReport:
    as_of: str
    horizons: tuple[int, ...]
    due_count: int
    future_count: int
    completed_count: int
    due: tuple[DueRecommendationEvaluation, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "asOf": self.as_of,
            "horizons": list(self.horizons),
            "dueCount": self.due_count,
            "futureCount": self.future_count,
            "completedCount": self.completed_count,
            "due": [item.to_api_dict() for item in self.due],
        }


class RecommendationEvaluationScheduleService:
    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> None:
        if not horizons or any(int(value) <= 0 for value in horizons):
            raise ValueError("horizons debe contener días positivos.")
        normalized = tuple(sorted({int(value) for value in horizons}))
        self._database = database if database is not None else AthenaDatabase()
        self._history = RecommendationHistoryRepository(database=self._database)
        self._horizons = normalized

    def get_report(self, *, as_of: datetime) -> RecommendationEvaluationScheduleReport:
        self._history.initialize()
        as_of_utc = self._aware_utc(as_of)

        placeholders = ",".join("?" for _ in self._horizons)
        with self._database.connect() as connection:
            recommendations = connection.execute(
                """
                SELECT id, symbol, action, model_version, generated_at
                FROM athena_recommendations
                ORDER BY id
                """
            ).fetchall()
            outcomes = connection.execute(
                f"""
                SELECT recommendation_id, horizon_days
                FROM athena_recommendation_outcomes
                WHERE horizon_days IN ({placeholders})
                """,
                self._horizons,
            ).fetchall()

        completed = {
            (int(row["recommendation_id"]), int(row["horizon_days"]))
            for row in outcomes
        }

        due_items: list[DueRecommendationEvaluation] = []
        future_count = 0
        completed_count = 0

        for row in recommendations:
            generated = datetime.fromisoformat(str(row["generated_at"]))
            if generated.tzinfo is None or generated.utcoffset() is None:
                raise RuntimeError(
                    "Se encontró una recomendación histórica sin zona horaria."
                )
            generated_utc = generated.astimezone(timezone.utc)

            for horizon in self._horizons:
                key = (int(row["id"]), horizon)
                if key in completed:
                    completed_count += 1
                    continue

                due_at = generated_utc + timedelta(days=horizon)
                if due_at <= as_of_utc:
                    due_items.append(
                        DueRecommendationEvaluation(
                            recommendation_id=int(row["id"]),
                            symbol=str(row["symbol"]),
                            model_version=str(row["model_version"]),
                            action=str(row["action"]),
                            generated_at=generated_utc.isoformat(),
                            horizon_days=horizon,
                            due_at=due_at.isoformat(),
                        )
                    )
                else:
                    future_count += 1

        due_items.sort(key=lambda item: (item.due_at, item.recommendation_id))

        return RecommendationEvaluationScheduleReport(
            as_of=as_of_utc.isoformat(),
            horizons=self._horizons,
            due_count=len(due_items),
            future_count=future_count,
            completed_count=completed_count,
            due=tuple(due_items),
        )

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
