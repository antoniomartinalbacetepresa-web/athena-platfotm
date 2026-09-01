from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowRepository:
    """Persist calibration-only evidence snapshots, never investment advice.

    This storage is deliberately separate from `athena_recommendations`: shadow
    observations contain no BUY/HOLD/REDUCE/SELL action, score or conviction and
    therefore cannot silently become user-facing recommendations.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    data_cutoff_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    feature_schema_version TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    entry_price REAL NOT NULL CHECK (entry_price > 0),
                    entry_observed_at TEXT NOT NULL,
                    entry_retrieved_at TEXT NOT NULL,
                    benchmark_symbol TEXT,
                    evidence_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id)
                        REFERENCES instruments(id)
                        ON DELETE CASCADE,
                    CHECK (data_cutoff_at <= captured_at),
                    CHECK (entry_observed_at <= data_cutoff_at),
                    CHECK (entry_retrieved_at <= data_cutoff_at),
                    UNIQUE (
                        instrument_id,
                        data_cutoff_at,
                        feature_schema_version
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_snapshots_symbol_cutoff
                ON athena_recommendation_shadow_snapshots(symbol, data_cutoff_at);

                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
                    due_at TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    exit_price REAL NOT NULL CHECK (exit_price > 0),
                    exit_observed_at TEXT NOT NULL,
                    exit_retrieved_at TEXT NOT NULL,
                    realized_return REAL NOT NULL,
                    benchmark_return REAL,
                    excess_return REAL,
                    source_provider TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (snapshot_id)
                        REFERENCES athena_recommendation_shadow_snapshots(id)
                        ON DELETE CASCADE,
                    CHECK (due_at <= evaluated_at),
                    CHECK (exit_observed_at >= due_at),
                    CHECK (exit_retrieved_at <= evaluated_at),
                    UNIQUE (snapshot_id, horizon_days)
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_outcomes_snapshot
                ON athena_recommendation_shadow_outcomes(snapshot_id, horizon_days);
                """
            )

    def create_snapshot(
        self,
        *,
        instrument_id: int,
        symbol: str,
        data_cutoff_at: datetime,
        captured_at: datetime,
        feature_schema_version: str,
        evidence_status: str,
        entry_price: float,
        entry_observed_at: datetime,
        entry_retrieved_at: datetime,
        evidence_snapshot: dict[str, Any],
        benchmark_symbol: str | None = None,
    ) -> int:
        self.initialize()
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        schema_version = self._required_text(
            feature_schema_version,
            "feature_schema_version",
        )
        status = self._required_text(evidence_status, "evidence_status")
        cutoff = self._aware_utc(data_cutoff_at, "data_cutoff_at")
        captured = self._aware_utc(captured_at, "captured_at")
        observed = self._aware_utc(entry_observed_at, "entry_observed_at")
        retrieved = self._aware_utc(entry_retrieved_at, "entry_retrieved_at")
        price = float(entry_price)
        if price <= 0:
            raise ValueError("entry_price debe ser positivo.")
        if captured < cutoff:
            raise ValueError("captured_at no puede ser anterior a data_cutoff_at.")
        if observed > cutoff:
            raise ValueError("entry_observed_at no puede superar data_cutoff_at.")
        if retrieved > cutoff:
            raise ValueError("entry_retrieved_at no puede superar data_cutoff_at.")
        benchmark = self._optional_symbol(benchmark_symbol)
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_shadow_snapshots (
                    instrument_id,
                    symbol,
                    data_cutoff_at,
                    captured_at,
                    feature_schema_version,
                    evidence_status,
                    entry_price,
                    entry_observed_at,
                    entry_retrieved_at,
                    benchmark_symbol,
                    evidence_snapshot_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    normalized_symbol,
                    cutoff.isoformat(),
                    captured.isoformat(),
                    schema_version,
                    status,
                    price,
                    observed.isoformat(),
                    retrieved.isoformat(),
                    benchmark,
                    json.dumps(evidence_snapshot, sort_keys=True, ensure_ascii=False),
                    now,
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir el snapshot en sombra.")
        return int(cursor.lastrowid)

    def record_outcome(
        self,
        *,
        snapshot_id: int,
        horizon_days: int,
        due_at: datetime,
        evaluated_at: datetime,
        exit_price: float,
        exit_observed_at: datetime,
        exit_retrieved_at: datetime,
        source_provider: str,
        benchmark_return: float | None = None,
    ) -> int:
        self.initialize()
        if snapshot_id <= 0:
            raise ValueError("snapshot_id debe ser positivo.")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")
        due = self._aware_utc(due_at, "due_at")
        evaluated = self._aware_utc(evaluated_at, "evaluated_at")
        observed = self._aware_utc(exit_observed_at, "exit_observed_at")
        retrieved = self._aware_utc(exit_retrieved_at, "exit_retrieved_at")
        if evaluated < due:
            raise ValueError("evaluated_at no puede ser anterior a due_at.")
        if observed < due:
            raise ValueError("exit_observed_at no puede ser anterior a due_at.")
        if retrieved > evaluated:
            raise ValueError("exit_retrieved_at no puede superar evaluated_at.")
        price = float(exit_price)
        if price <= 0:
            raise ValueError("exit_price debe ser positivo.")
        provider = self._required_text(source_provider, "source_provider")

        with self._database.connect() as connection:
            snapshot = connection.execute(
                """
                SELECT entry_price
                FROM athena_recommendation_shadow_snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise ValueError("El snapshot en sombra no existe.")
            entry_price = float(snapshot["entry_price"])
            realized_return = (price / entry_price) - 1.0
            excess_return = (
                realized_return - float(benchmark_return)
                if benchmark_return is not None
                else None
            )
            cursor = connection.execute(
                """
                INSERT INTO athena_recommendation_shadow_outcomes (
                    snapshot_id,
                    horizon_days,
                    due_at,
                    evaluated_at,
                    exit_price,
                    exit_observed_at,
                    exit_retrieved_at,
                    realized_return,
                    benchmark_return,
                    excess_return,
                    source_provider,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    int(horizon_days),
                    due.isoformat(),
                    evaluated.isoformat(),
                    price,
                    observed.isoformat(),
                    retrieved.isoformat(),
                    realized_return,
                    benchmark_return,
                    excess_return,
                    provider,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("No se pudo persistir el resultado en sombra.")
        return int(cursor.lastrowid)

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        self.initialize()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["evidence_snapshot"] = json.loads(
            result.pop("evidence_snapshot_json")
        )
        return result

    def list_outcomes(self, snapshot_id: int) -> list[dict[str, Any]]:
        self.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_outcomes
                WHERE snapshot_id = ?
                ORDER BY horizon_days
                """,
                (snapshot_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _required_text(self, value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _optional_symbol(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
