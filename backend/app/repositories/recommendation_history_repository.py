from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationHistoryRepository:
    """Stores immutable point-in-time ATHENA recommendations and outcomes."""

    _ACTIONS = frozenset({"buy", "hold", "reduce", "sell"})

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER,
                    canonical_issuer_id INTEGER,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL
                        CHECK (action IN ('buy', 'hold', 'reduce', 'sell')),
                    score REAL NOT NULL
                        CHECK (score >= 0 AND score <= 100),
                    conviction REAL NOT NULL
                        CHECK (conviction >= 0 AND conviction <= 1),
                    risk_score REAL
                        CHECK (
                            risk_score IS NULL
                            OR (risk_score >= 0 AND risk_score <= 100)
                        ),
                    horizon_days INTEGER NOT NULL
                        CHECK (horizon_days > 0),
                    generated_at TEXT NOT NULL,
                    data_cutoff_at TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    rationale_json TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id)
                        REFERENCES instruments(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY (canonical_issuer_id)
                        REFERENCES canonical_issuers(id)
                        ON DELETE SET NULL,
                    CHECK (data_cutoff_at <= generated_at)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_athena_recommendations_symbol_time
                ON athena_recommendations(symbol, generated_at);

                CREATE INDEX IF NOT EXISTS
                    idx_athena_recommendations_issuer_time
                ON athena_recommendations(canonical_issuer_id, generated_at);

                CREATE TABLE IF NOT EXISTS athena_recommendation_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id INTEGER NOT NULL,
                    horizon_days INTEGER NOT NULL
                        CHECK (horizon_days > 0),
                    evaluated_at TEXT NOT NULL,
                    entry_price REAL NOT NULL CHECK (entry_price > 0),
                    exit_price REAL NOT NULL CHECK (exit_price > 0),
                    realized_return REAL NOT NULL,
                    benchmark_return REAL,
                    excess_return REAL,
                    max_drawdown REAL,
                    source_provider TEXT NOT NULL,
                    source_timestamp TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (recommendation_id)
                        REFERENCES athena_recommendations(id)
                        ON DELETE CASCADE,
                    UNIQUE (recommendation_id, horizon_days)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_athena_outcomes_recommendation
                ON athena_recommendation_outcomes(recommendation_id);
                """
            )

    def create_recommendation(
        self,
        *,
        symbol: str,
        action: str,
        score: float,
        conviction: float,
        horizon_days: int,
        generated_at: datetime,
        data_cutoff_at: datetime,
        model_version: str,
        rationale: dict[str, Any],
        input_snapshot: dict[str, Any],
        instrument_id: int | None = None,
        canonical_issuer_id: int | None = None,
        risk_score: float | None = None,
    ) -> int:
        self.initialize()
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        normalized_action = self._required_text(action, "action").lower()
        if normalized_action not in self._ACTIONS:
            raise ValueError("action debe ser buy, hold, reduce o sell.")
        normalized_score = self._bounded(score, "score", 0.0, 100.0)
        normalized_conviction = self._bounded(
            conviction, "conviction", 0.0, 1.0
        )
        normalized_risk = (
            None
            if risk_score is None
            else self._bounded(risk_score, "risk_score", 0.0, 100.0)
        )
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser mayor que 0.")

        generated = self._utc_iso(generated_at, "generated_at")
        cutoff = self._utc_iso(data_cutoff_at, "data_cutoff_at")
        if cutoff > generated:
            raise ValueError("data_cutoff_at no puede ser posterior a generated_at.")

        version = self._required_text(model_version, "model_version")
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO athena_recommendations (
                    instrument_id,
                    canonical_issuer_id,
                    symbol,
                    action,
                    score,
                    conviction,
                    risk_score,
                    horizon_days,
                    generated_at,
                    data_cutoff_at,
                    model_version,
                    rationale_json,
                    input_snapshot_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    canonical_issuer_id,
                    normalized_symbol,
                    normalized_action,
                    normalized_score,
                    normalized_conviction,
                    normalized_risk,
                    int(horizon_days),
                    generated,
                    cutoff,
                    version,
                    json.dumps(rationale, sort_keys=True, ensure_ascii=False),
                    json.dumps(input_snapshot, sort_keys=True, ensure_ascii=False),
                    now,
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir la recomendación.")
        return int(cursor.lastrowid)

    def record_outcome(
        self,
        *,
        recommendation_id: int,
        horizon_days: int,
        evaluated_at: datetime,
        entry_price: float,
        exit_price: float,
        source_provider: str,
        benchmark_return: float | None = None,
        max_drawdown: float | None = None,
        source_timestamp: datetime | None = None,
    ) -> int:
        self.initialize()
        if recommendation_id <= 0:
            raise ValueError("recommendation_id debe ser positivo.")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser mayor que 0.")
        if entry_price <= 0 or exit_price <= 0:
            raise ValueError("entry_price y exit_price deben ser positivos.")

        evaluated = self._utc_iso(evaluated_at, "evaluated_at")
        provider = self._required_text(source_provider, "source_provider")
        source_time = (
            self._utc_iso(source_timestamp, "source_timestamp")
            if source_timestamp is not None
            else None
        )

        with self._database.connect() as connection:
            recommendation = connection.execute(
                """
                SELECT generated_at
                FROM athena_recommendations
                WHERE id = ?
                """,
                (recommendation_id,),
            ).fetchone()
            if recommendation is None:
                raise ValueError("La recomendación indicada no existe.")
            if evaluated <= str(recommendation["generated_at"]):
                raise ValueError(
                    "evaluated_at debe ser posterior a la recomendación."
                )

            realized_return = (float(exit_price) / float(entry_price)) - 1.0
            excess_return = (
                realized_return - float(benchmark_return)
                if benchmark_return is not None
                else None
            )
            now = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_outcomes (
                    recommendation_id,
                    horizon_days,
                    evaluated_at,
                    entry_price,
                    exit_price,
                    realized_return,
                    benchmark_return,
                    excess_return,
                    max_drawdown,
                    source_provider,
                    source_timestamp,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    int(horizon_days),
                    evaluated,
                    float(entry_price),
                    float(exit_price),
                    realized_return,
                    benchmark_return,
                    excess_return,
                    max_drawdown,
                    provider,
                    source_time,
                    now,
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir el resultado.")
        return int(cursor.lastrowid)

    def get_recommendation(self, recommendation_id: int) -> dict[str, Any] | None:
        self.initialize()
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_recommendations WHERE id = ?",
                (recommendation_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["rationale"] = json.loads(result.pop("rationale_json"))
        result["input_snapshot"] = json.loads(result.pop("input_snapshot_json"))
        return result

    def list_outcomes(self, recommendation_id: int) -> list[dict[str, Any]]:
        self.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_outcomes
                WHERE recommendation_id = ?
                ORDER BY horizon_days
                """,
                (recommendation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _required_text(self, value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _bounded(self, value: float, field: str, low: float, high: float) -> float:
        result = float(value)
        if result < low or result > high:
            raise ValueError(f"{field} debe estar entre {low} y {high}.")
        return result

    def _utc_iso(self, value: datetime, field: str) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc).isoformat()
