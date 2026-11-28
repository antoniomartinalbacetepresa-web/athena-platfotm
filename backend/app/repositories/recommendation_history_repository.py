from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


class RecommendationHistoryRepository:
    """Stores immutable point-in-time ATHENA recommendations and outcomes."""

    _ACTIONS = frozenset({"buy", "hold", "reduce", "sell"})

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        # Recommendations may optionally reference a canonical issuer. Ensure the
        # referenced table exists before SQLite validates that foreign key, even
        # when a particular recommendation has canonical_issuer_id = NULL.
        IssuerIdentityRepository(database=self._database).initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER,
                    canonical_issuer_id INTEGER,
                    symbol TEXT NOT NULL,
                    benchmark_symbol TEXT,
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
                    benchmark_evidence_json TEXT,
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

            recommendation_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(athena_recommendations)"
                ).fetchall()
            }
            if "benchmark_symbol" not in recommendation_columns:
                connection.execute(
                    "ALTER TABLE athena_recommendations ADD COLUMN benchmark_symbol TEXT"
                )
            outcome_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(athena_recommendation_outcomes)"
                ).fetchall()
            }
            if "benchmark_evidence_json" not in outcome_columns:
                connection.execute(
                    "ALTER TABLE athena_recommendation_outcomes "
                    "ADD COLUMN benchmark_evidence_json TEXT"
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
        benchmark_symbol: str | None = None,
    ) -> int:
        self.initialize()
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        normalized_benchmark = self._optional_symbol(benchmark_symbol)
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
                    benchmark_symbol,
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    canonical_issuer_id,
                    normalized_symbol,
                    normalized_benchmark,
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
        benchmark_evidence: dict[str, Any] | None = None,
        max_drawdown: float | None = None,
        source_timestamp: datetime | None = None,
    ) -> int:
        self.initialize()
        if recommendation_id <= 0:
            raise ValueError("recommendation_id debe ser positivo.")
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser mayor que 0.")
        normalized_entry_price = self._positive_finite(entry_price, "entry_price")
        normalized_exit_price = self._positive_finite(exit_price, "exit_price")

        evaluated_at_utc = self._aware_utc(evaluated_at, "evaluated_at")
        evaluated = evaluated_at_utc.isoformat()
        provider = self._required_text(source_provider, "source_provider")
        source_time = (
            self._utc_iso(source_timestamp, "source_timestamp")
            if source_timestamp is not None
            else None
        )

        with self._database.connect() as connection:
            recommendation = connection.execute(
                """
                SELECT generated_at, benchmark_symbol
                FROM athena_recommendations
                WHERE id = ?
                """,
                (recommendation_id,),
            ).fetchone()
            if recommendation is None:
                raise ValueError("La recomendación indicada no existe.")

            generated_at_utc = self._parse_utc(
                str(recommendation["generated_at"]),
                "generated_at",
            )
            due_at = generated_at_utc + timedelta(days=int(horizon_days))
            if evaluated_at_utc < due_at:
                raise ValueError(
                    "evaluated_at no puede ser anterior al vencimiento del horizonte."
                )

            frozen_benchmark = self._optional_symbol(recommendation["benchmark_symbol"])
            normalized_benchmark_evidence: dict[str, Any] | None = None
            resolved_benchmark_return: float | None = None
            if benchmark_evidence is not None:
                normalized_benchmark_evidence, resolved_benchmark_return = (
                    self._validate_benchmark_evidence(
                        benchmark_evidence,
                        frozen_symbol=frozen_benchmark,
                        generated_at=generated_at_utc,
                        due_at=due_at,
                        evaluated_at=evaluated_at_utc,
                    )
                )
                if benchmark_return is not None:
                    supplied = self._finite(benchmark_return, "benchmark_return")
                    if not math.isclose(
                        supplied,
                        resolved_benchmark_return,
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    ):
                        raise ValueError(
                            "benchmark_return no coincide con la evidencia del benchmark."
                        )
            elif benchmark_return is not None:
                raise ValueError(
                    "benchmark_return requiere evidencia trazable del benchmark congelado."
                )

            realized_return = (normalized_exit_price / normalized_entry_price) - 1.0
            excess_return = (
                realized_return - resolved_benchmark_return
                if resolved_benchmark_return is not None
                else None
            )
            normalized_drawdown = (
                None
                if max_drawdown is None
                else self._finite(max_drawdown, "max_drawdown")
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
                    benchmark_evidence_json,
                    max_drawdown,
                    source_provider,
                    source_timestamp,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    int(horizon_days),
                    evaluated,
                    normalized_entry_price,
                    normalized_exit_price,
                    realized_return,
                    resolved_benchmark_return,
                    excess_return,
                    (
                        json.dumps(
                            normalized_benchmark_evidence,
                            sort_keys=True,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        if normalized_benchmark_evidence is not None
                        else None
                    ),
                    normalized_drawdown,
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
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw_evidence = item.pop("benchmark_evidence_json", None)
            item["benchmark_evidence"] = (
                json.loads(raw_evidence) if raw_evidence is not None else None
            )
            result.append(item)
        return result

    def _validate_benchmark_evidence(
        self,
        evidence: dict[str, Any],
        *,
        frozen_symbol: str | None,
        generated_at: datetime,
        due_at: datetime,
        evaluated_at: datetime,
    ) -> tuple[dict[str, Any], float]:
        if not isinstance(evidence, dict):
            raise ValueError("benchmark_evidence debe ser un objeto.")
        if frozen_symbol is None:
            raise ValueError("No puede persistirse benchmark sin símbolo congelado.")
        if evidence.get("status") != "resolved":
            raise ValueError("La evidencia del benchmark debe estar resuelta.")
        symbol = self._optional_symbol(evidence.get("benchmarkSymbol"))
        if symbol != frozen_symbol:
            raise ValueError("La evidencia pertenece a otro benchmark.")
        instrument_id = evidence.get("benchmarkInstrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("benchmarkInstrumentId debe ser entero positivo.")
        entry_price = self._positive_finite(evidence.get("entryPrice"), "benchmark.entryPrice")
        exit_price = self._positive_finite(evidence.get("exitPrice"), "benchmark.exitPrice")
        calculated_return = (exit_price / entry_price) - 1.0
        reported_return = self._finite(
            evidence.get("benchmarkReturn"), "benchmark.benchmarkReturn"
        )
        if not math.isclose(
            calculated_return, reported_return, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("benchmarkReturn no coincide con los precios preservados.")

        entry_observed = self._parse_utc_value(
            evidence.get("entryObservedAt"), "benchmark.entryObservedAt"
        )
        exit_observed = self._parse_utc_value(
            evidence.get("exitObservedAt"), "benchmark.exitObservedAt"
        )
        entry_retrieved = self._parse_utc_value(
            evidence.get("entryRetrievedAt"), "benchmark.entryRetrievedAt"
        )
        exit_retrieved = self._parse_utc_value(
            evidence.get("exitRetrievedAt"), "benchmark.exitRetrievedAt"
        )
        if entry_observed < generated_at or entry_observed > due_at:
            raise ValueError("La observación de entrada del benchmark está fuera de ventana.")
        if exit_observed < due_at or exit_observed > evaluated_at:
            raise ValueError("La observación de salida del benchmark está fuera de ventana.")
        if entry_retrieved > evaluated_at or exit_retrieved > evaluated_at:
            raise ValueError("La evidencia del benchmark fue recuperada después de as_of.")
        entry_provider = self._required_text(
            evidence.get("entrySourceProvider"), "benchmark.entrySourceProvider"
        )
        exit_provider = self._required_text(
            evidence.get("exitSourceProvider"), "benchmark.exitSourceProvider"
        )
        normalized = {
            "status": "resolved",
            "benchmarkSymbol": symbol,
            "benchmarkInstrumentId": instrument_id,
            "entryPrice": entry_price,
            "exitPrice": exit_price,
            "benchmarkReturn": calculated_return,
            "entryObservedAt": entry_observed.isoformat(),
            "exitObservedAt": exit_observed.isoformat(),
            "entryRetrievedAt": entry_retrieved.isoformat(),
            "exitRetrievedAt": exit_retrieved.isoformat(),
            "entrySourceProvider": entry_provider,
            "exitSourceProvider": exit_provider,
            "policy": evidence.get("policy") if isinstance(evidence.get("policy"), dict) else {},
        }
        return normalized, calculated_return

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _optional_symbol(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    def _bounded(self, value: float, field: str, low: float, high: float) -> float:
        result = self._finite(value, field)
        if result < low or result > high:
            raise ValueError(f"{field} debe estar entre {low} y {high}.")
        return result

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _utc_iso(self, value: datetime, field: str) -> str:
        return self._aware_utc(value, field).isoformat()

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_utc(self, value: str, field: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"{field} histórico debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _parse_utc_value(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)
