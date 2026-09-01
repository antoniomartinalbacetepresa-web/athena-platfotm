from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class RecommendationBenchmarkReturnResult:
    status: str
    benchmark_symbol: str | None
    benchmark_instrument_id: int | None
    entry_price: float | None
    exit_price: float | None
    benchmark_return: float | None
    entry_observed_at: str | None
    exit_observed_at: str | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "benchmarkSymbol": self.benchmark_symbol,
            "benchmarkInstrumentId": self.benchmark_instrument_id,
            "entryPrice": self.entry_price,
            "exitPrice": self.exit_price,
            "benchmarkReturn": self.benchmark_return,
            "entryObservedAt": self.entry_observed_at,
            "exitObservedAt": self.exit_observed_at,
            "policy": {
                "retrievalCutoff": "retrieved_at_not_after_evaluation_as_of",
                "duplicateObservation": "latest_retrieved_at_before_as_of",
            },
        }


class RecommendationBenchmarkReturnService:
    """Calculates benchmark returns only from an explicit frozen benchmark."""

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def calculate(
        self,
        *,
        benchmark_symbol: str | None,
        generated_at: datetime,
        due_at: datetime,
        as_of: datetime,
    ) -> RecommendationBenchmarkReturnResult:
        normalized_symbol = self._optional_symbol(benchmark_symbol)
        if normalized_symbol is None:
            return self._empty("benchmark_not_declared", None)

        generated = self._aware_utc(generated_at, "generated_at")
        due = self._aware_utc(due_at, "due_at")
        effective_as_of = self._aware_utc(as_of, "as_of")
        if due <= generated:
            raise ValueError("due_at debe ser posterior a generated_at.")
        if effective_as_of < due:
            raise ValueError("as_of no puede ser anterior a due_at.")

        instrument_ids = self._active_instrument_ids(normalized_symbol)
        if not instrument_ids:
            return self._empty("benchmark_instrument_not_found", normalized_symbol)
        if len(instrument_ids) != 1:
            return self._empty("benchmark_instrument_ambiguous", normalized_symbol)

        instrument_id = instrument_ids[0]
        entry = self._first_price_in_window(
            instrument_id=instrument_id,
            at_or_after=generated,
            not_after=due,
            knowledge_cutoff=effective_as_of,
        )
        if entry is None:
            return self._empty(
                "benchmark_entry_price_missing",
                normalized_symbol,
                instrument_id,
            )

        exit_observation = self._first_price_in_window(
            instrument_id=instrument_id,
            at_or_after=due,
            not_after=effective_as_of,
            knowledge_cutoff=effective_as_of,
        )
        if exit_observation is None:
            return self._empty(
                "benchmark_exit_price_missing",
                normalized_symbol,
                instrument_id,
            )

        entry_price = float(entry["price"])
        exit_price = float(exit_observation["price"])
        return RecommendationBenchmarkReturnResult(
            status="resolved",
            benchmark_symbol=normalized_symbol,
            benchmark_instrument_id=instrument_id,
            entry_price=entry_price,
            exit_price=exit_price,
            benchmark_return=(exit_price / entry_price) - 1.0,
            entry_observed_at=str(entry["observed_at"]),
            exit_observed_at=str(exit_observation["observed_at"]),
        )

    def _active_instrument_ids(self, symbol: str) -> tuple[int, ...]:
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM instruments
                WHERE is_active = 1
                  AND UPPER(symbol) = ?
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()
        return tuple(int(row["id"]) for row in rows)

    def _first_price_in_window(
        self,
        *,
        instrument_id: int,
        at_or_after: datetime,
        not_after: datetime,
        knowledge_cutoff: datetime,
    ) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
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
                SELECT observed_at, price, retrieved_at
                FROM eligible
                WHERE row_rank = 1
                ORDER BY observed_at ASC
                LIMIT 1
                """,
                (
                    instrument_id,
                    at_or_after.astimezone(timezone.utc).isoformat(),
                    not_after.astimezone(timezone.utc).isoformat(),
                    knowledge_cutoff.astimezone(timezone.utc).isoformat(),
                ),
            ).fetchone()
        if row is None:
            return None
        return {
            "observed_at": str(row["observed_at"]),
            "price": float(row["price"]),
            "retrieved_at": str(row["retrieved_at"]),
        }

    def _empty(
        self,
        status: str,
        benchmark_symbol: str | None,
        benchmark_instrument_id: int | None = None,
    ) -> RecommendationBenchmarkReturnResult:
        return RecommendationBenchmarkReturnResult(
            status=status,
            benchmark_symbol=benchmark_symbol,
            benchmark_instrument_id=benchmark_instrument_id,
            entry_price=None,
            exit_price=None,
            benchmark_return=None,
            entry_observed_at=None,
            exit_observed_at=None,
        )

    def _optional_symbol(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
