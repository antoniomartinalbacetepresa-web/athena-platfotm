from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_benchmark_return_service import (
    RecommendationBenchmarkReturnService,
)
from app.services.recommendation_evaluation_schedule_service import (
    RecommendationEvaluationScheduleService,
)


@dataclass(frozen=True)
class RecommendationOutcomeEvaluationReport:
    due_count: int
    evaluated_count: int
    skipped_missing_instrument: int
    skipped_missing_entry_price: int
    skipped_missing_exit_price: int
    skipped_invalid_price_window: int
    skipped_missing_benchmark: int
    evaluated: tuple[dict[str, Any], ...]

    @property
    def skipped_count(self) -> int:
        return (
            self.skipped_missing_instrument
            + self.skipped_missing_entry_price
            + self.skipped_missing_exit_price
            + self.skipped_invalid_price_window
            + self.skipped_missing_benchmark
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "point_in_time_evaluation",
            "dueCount": self.due_count,
            "evaluatedCount": self.evaluated_count,
            "skippedCount": self.skipped_count,
            "skipped": {
                "missingInstrument": self.skipped_missing_instrument,
                "missingEntryPrice": self.skipped_missing_entry_price,
                "missingExitPrice": self.skipped_missing_exit_price,
                "invalidPriceWindow": self.skipped_invalid_price_window,
                "missingFrozenBenchmark": self.skipped_missing_benchmark,
            },
            "evaluated": [dict(item) for item in self.evaluated],
            "pricePolicy": "raw_close_first_adjusted_close_fallback",
            "temporalWindowPolicy": "entry_before_due_exit_not_after_as_of",
            "knowledgePolicy": "retrieved_at_not_after_evaluation_as_of",
            "evaluationTimestampPolicy": "persist_actual_knowledge_as_of_not_exit_observation_time",
            "duplicateObservationPolicy": "latest_retrieved_at_before_as_of",
            "benchmarkStatus": "evaluated_when_explicit_frozen_benchmark_is_resolvable",
            "benchmarkPersistencePolicy": "declared_frozen_benchmark_must_resolve_before_outcome_persistence",
            "benchmarkEvidencePolicy": "exact_observation_and_retrieval_provenance_persisted",
        }


class RecommendationOutcomeEvaluationService:
    """Evaluate due recommendations from persisted PIT prices without backfill leakage.

    ``evaluated_at`` represents when the evidence was actually knowable, not merely
    the timestamp of the selected exit observation. A recommendation that froze a
    benchmark is persisted only when that benchmark can be resolved atomically with
    exact observation/retrieval provenance. This prevents partial outcome rows from
    permanently consuming the unique horizon slot.
    """

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._history = RecommendationHistoryRepository(database=self._database)
        self._schedule = RecommendationEvaluationScheduleService(
            database=self._database
        )
        self._benchmark = RecommendationBenchmarkReturnService(
            database=self._database
        )

    def evaluate_due(
        self,
        *,
        as_of: datetime,
        source_provider: str = "athena_market_observations",
    ) -> RecommendationOutcomeEvaluationReport:
        as_of_utc = self._aware_utc(as_of)
        schedule = self._schedule.get_report(as_of=as_of_utc)

        evaluated: list[dict[str, Any]] = []
        missing_instrument = 0
        missing_entry = 0
        missing_exit = 0
        invalid_window = 0
        missing_benchmark = 0

        for due in schedule.due:
            recommendation = self._history.get_recommendation(
                due.recommendation_id
            )
            if recommendation is None:
                continue

            instrument_id = recommendation.get("instrument_id")
            if instrument_id is None:
                missing_instrument += 1
                continue

            generated_at = datetime.fromisoformat(
                str(recommendation["generated_at"])
            ).astimezone(timezone.utc)
            due_at = datetime.fromisoformat(due.due_at).astimezone(timezone.utc)

            entry = self._first_price_in_window(
                instrument_id=int(instrument_id),
                at_or_after=generated_at,
                not_after=due_at,
                knowledge_cutoff=as_of_utc,
            )
            if entry is None:
                missing_entry += 1
                continue

            exit_observation = self._first_price_in_window(
                instrument_id=int(instrument_id),
                at_or_after=due_at,
                not_after=as_of_utc,
                knowledge_cutoff=as_of_utc,
            )
            if exit_observation is None:
                missing_exit += 1
                continue

            entry_time = datetime.fromisoformat(entry["observed_at"])
            exit_time = datetime.fromisoformat(exit_observation["observed_at"])
            if (
                entry_time >= due_at
                or exit_time < due_at
                or exit_time > as_of_utc
                or exit_time <= entry_time
            ):
                invalid_window += 1
                continue

            entry_price = float(entry["price"])
            exit_price = float(exit_observation["price"])
            max_drawdown = self._max_drawdown(
                instrument_id=int(instrument_id),
                start_at=entry_time,
                end_at=exit_time,
                knowledge_cutoff=as_of_utc,
                entry_price=entry_price,
            )
            frozen_benchmark_symbol = self._optional_symbol(
                recommendation.get("benchmark_symbol")
            )
            benchmark = self._benchmark.calculate(
                benchmark_symbol=frozen_benchmark_symbol,
                generated_at=generated_at,
                due_at=due_at,
                as_of=as_of_utc,
            )
            if frozen_benchmark_symbol is not None and benchmark.status != "resolved":
                missing_benchmark += 1
                continue

            benchmark_return = (
                benchmark.benchmark_return
                if benchmark.status == "resolved"
                else None
            )
            benchmark_evidence = (
                benchmark.to_api_dict() if benchmark.status == "resolved" else None
            )

            outcome_id = self._history.record_outcome(
                recommendation_id=due.recommendation_id,
                horizon_days=due.horizon_days,
                evaluated_at=as_of_utc,
                entry_price=entry_price,
                exit_price=exit_price,
                source_provider=source_provider,
                benchmark_return=benchmark_return,
                benchmark_evidence=benchmark_evidence,
                max_drawdown=max_drawdown,
                source_timestamp=datetime.fromisoformat(exit_observation["retrieved_at"]),
            )
            realized_return = (exit_price / entry_price) - 1.0
            evaluated.append(
                {
                    "outcomeId": outcome_id,
                    "recommendationId": due.recommendation_id,
                    "symbol": due.symbol,
                    "horizonDays": due.horizon_days,
                    "dueAt": due_at.isoformat(),
                    "evaluatedAt": as_of_utc.isoformat(),
                    "entryObservedAt": entry_time.astimezone(timezone.utc).isoformat(),
                    "entryRetrievedAt": str(entry["retrieved_at"]),
                    "exitObservedAt": exit_time.astimezone(timezone.utc).isoformat(),
                    "exitRetrievedAt": str(exit_observation["retrieved_at"]),
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "realizedReturn": realized_return,
                    "maxDrawdown": max_drawdown,
                    "benchmarkStatus": benchmark.status,
                    "benchmarkSymbol": benchmark.benchmark_symbol,
                    "benchmarkReturn": benchmark_return,
                    "benchmarkEvidence": benchmark_evidence,
                    "excessReturn": (
                        realized_return - benchmark_return
                        if benchmark_return is not None
                        else None
                    ),
                }
            )

        return RecommendationOutcomeEvaluationReport(
            due_count=schedule.due_count,
            evaluated_count=len(evaluated),
            skipped_missing_instrument=missing_instrument,
            skipped_missing_entry_price=missing_entry,
            skipped_missing_exit_price=missing_exit,
            skipped_invalid_price_window=invalid_window,
            skipped_missing_benchmark=missing_benchmark,
            evaluated=tuple(evaluated),
        )

    def _first_price_in_window(
        self,
        *,
        instrument_id: int,
        at_or_after: datetime,
        not_after: datetime,
        knowledge_cutoff: datetime,
    ) -> dict[str, Any] | None:
        start = at_or_after.astimezone(timezone.utc)
        end = not_after.astimezone(timezone.utc)
        cutoff = knowledge_cutoff.astimezone(timezone.utc)
        if end < start:
            return None

        with self._database.connect() as connection:
            row = connection.execute(
                """
                WITH eligible AS (
                    SELECT
                        observed_at,
                        COALESCE(close, adjusted_close) AS price,
                        retrieved_at,
                        source_provider,
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY observed_at
                            ORDER BY retrieved_at DESC, id DESC
                        ) AS row_rank
                    FROM market_observations
                    WHERE instrument_id = ?
                      AND observed_at >= ?
                      AND observed_at <= ?
                      AND retrieved_at <= ?
                      AND COALESCE(close, adjusted_close) IS NOT NULL
                      AND COALESCE(close, adjusted_close) > 0
                )
                SELECT observed_at, price, retrieved_at, source_provider
                FROM eligible
                WHERE row_rank = 1
                ORDER BY observed_at ASC
                LIMIT 1
                """,
                (
                    instrument_id,
                    start.isoformat(),
                    end.isoformat(),
                    cutoff.isoformat(),
                ),
            ).fetchone()
        if row is None:
            return None
        return {
            "observed_at": str(row["observed_at"]),
            "price": float(row["price"]),
            "retrieved_at": str(row["retrieved_at"]),
            "source_provider": str(row["source_provider"]),
        }

    def _max_drawdown(
        self,
        *,
        instrument_id: int,
        start_at: datetime,
        end_at: datetime,
        knowledge_cutoff: datetime,
        entry_price: float,
    ) -> float | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                WITH eligible AS (
                    SELECT
                        observed_at,
                        COALESCE(close, adjusted_close) AS price,
                        retrieved_at,
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY observed_at
                            ORDER BY retrieved_at DESC, id DESC
                        ) AS row_rank
                    FROM market_observations
                    WHERE instrument_id = ?
                      AND observed_at >= ?
                      AND observed_at <= ?
                      AND retrieved_at <= ?
                      AND COALESCE(close, adjusted_close) IS NOT NULL
                      AND COALESCE(close, adjusted_close) > 0
                )
                SELECT observed_at, price
                FROM eligible
                WHERE row_rank = 1
                ORDER BY observed_at ASC
                """,
                (
                    instrument_id,
                    start_at.astimezone(timezone.utc).isoformat(),
                    end_at.astimezone(timezone.utc).isoformat(),
                    knowledge_cutoff.astimezone(timezone.utc).isoformat(),
                ),
            ).fetchall()

        if not rows:
            return None

        peak = float(entry_price)
        max_drawdown = 0.0
        for row in rows:
            price = float(row["price"])
            if price > peak:
                peak = price
            drawdown = (price / peak) - 1.0
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        return max_drawdown

    def _optional_symbol(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
