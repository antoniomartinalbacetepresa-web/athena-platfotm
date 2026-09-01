from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)
from app.services.recommendation_benchmark_return_service import (
    RecommendationBenchmarkReturnService,
)


class RecommendationShadowOutcomeService:
    """Evaluate calibration-only snapshots without creating advisory labels."""

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = RecommendationShadowRepository(database=self._database)
        self._benchmark = RecommendationBenchmarkReturnService(database=self._database)

    def evaluate_snapshot(
        self,
        *,
        snapshot_id: int,
        as_of: datetime,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        if snapshot_id <= 0:
            raise ValueError("snapshot_id debe ser positivo.")
        effective_as_of = self._aware_utc(as_of, "as_of")
        normalized_horizons = self._horizons(horizons)
        snapshot = self._repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError("El snapshot en sombra no existe.")

        cutoff = self._parse_aware(snapshot["data_cutoff_at"], "data_cutoff_at")
        instrument_id = int(snapshot["instrument_id"])
        existing = {
            int(row["horizon_days"])
            for row in self._repository.list_outcomes(snapshot_id)
        }
        evaluated: list[dict[str, Any]] = []
        pending: list[int] = []
        missing_price: list[int] = []

        for horizon in normalized_horizons:
            if horizon in existing:
                continue
            due_at = cutoff + timedelta(days=horizon)
            if effective_as_of < due_at:
                pending.append(horizon)
                continue
            exit_observation = self._first_price_at_or_after(
                instrument_id=instrument_id,
                due_at=due_at,
                as_of=effective_as_of,
            )
            if exit_observation is None:
                missing_price.append(horizon)
                continue

            benchmark = self._benchmark.calculate(
                benchmark_symbol=snapshot.get("benchmark_symbol"),
                generated_at=cutoff,
                due_at=due_at,
                as_of=effective_as_of,
            )
            benchmark_return = (
                benchmark.benchmark_return if benchmark.status == "resolved" else None
            )
            exit_observed_at = self._parse_aware(
                exit_observation["observed_at"],
                "exit_observed_at",
            )
            exit_retrieved_at = self._parse_aware(
                exit_observation["retrieved_at"],
                "exit_retrieved_at",
            )
            outcome_id = self._repository.record_outcome(
                snapshot_id=snapshot_id,
                horizon_days=horizon,
                due_at=due_at,
                evaluated_at=effective_as_of,
                exit_price=float(exit_observation["price"]),
                exit_observed_at=exit_observed_at,
                exit_retrieved_at=exit_retrieved_at,
                source_provider=str(exit_observation["source_provider"]),
                benchmark_return=benchmark_return,
            )
            entry_price = float(snapshot["entry_price"])
            exit_price = float(exit_observation["price"])
            realized_return = (exit_price / entry_price) - 1.0
            evaluated.append(
                {
                    "outcomeId": outcome_id,
                    "snapshotId": snapshot_id,
                    "horizonDays": horizon,
                    "dueAt": due_at.isoformat(),
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "exitObservedAt": exit_observed_at.isoformat(),
                    "exitRetrievedAt": exit_retrieved_at.isoformat(),
                    "realizedReturn": realized_return,
                    "benchmarkStatus": benchmark.status,
                    "benchmarkSymbol": benchmark.benchmark_symbol,
                    "benchmarkReturn": benchmark_return,
                    "excessReturn": (
                        realized_return - benchmark_return
                        if benchmark_return is not None
                        else None
                    ),
                }
            )

        return {
            "status": "shadow_outcomes_evaluated",
            "snapshotId": snapshot_id,
            "symbol": snapshot["symbol"],
            "asOf": effective_as_of.isoformat(),
            "evaluated": evaluated,
            "pendingHorizons": pending,
            "missingPriceHorizons": missing_price,
            "alreadyEvaluatedHorizons": sorted(existing),
            "advisoryStatus": "no_advice",
            "policy": {
                "horizonsDays": list(normalized_horizons),
                "exit": "first_observation_at_or_after_due",
                "retrievalCutoff": "retrieved_at_not_after_evaluation_as_of",
                "duplicateObservation": "latest_retrieved_at_before_as_of",
                "benchmark": "explicit_frozen_symbol_only",
            },
        }

    def _first_price_at_or_after(
        self,
        *,
        instrument_id: int,
        due_at: datetime,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                WITH eligible AS (
                    SELECT
                        observed_at,
                        COALESCE(close, adjusted_close) AS price,
                        source_provider,
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
                SELECT observed_at, price, source_provider, retrieved_at
                FROM eligible
                WHERE row_rank = 1
                ORDER BY observed_at ASC
                LIMIT 1
                """,
                (
                    instrument_id,
                    due_at.astimezone(timezone.utc).isoformat(),
                    as_of.astimezone(timezone.utc).isoformat(),
                    as_of.astimezone(timezone.utc).isoformat(),
                ),
            ).fetchone()
        return dict(row) if row is not None else None

    def _horizons(self, values: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(sorted(set(int(value) for value in values)))
        if not normalized or any(value <= 0 for value in normalized):
            raise ValueError("Los horizontes deben ser enteros positivos.")
        return normalized

    def _parse_aware(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise RuntimeError(f"{field} histórico no es válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"{field} histórico debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
