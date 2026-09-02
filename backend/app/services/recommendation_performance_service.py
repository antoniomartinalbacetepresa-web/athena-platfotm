from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)


@dataclass(frozen=True)
class RecommendationPerformanceReport:
    sample_count: int
    model_version: str | None
    horizon_days: int | None
    average_realized_return: float | None
    average_excess_return: float | None
    directional_sample_count: int
    directional_success_count: int
    directional_accuracy: float | None
    by_action: dict[str, dict[str, Any]]
    conviction_buckets: tuple[dict[str, Any], ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "sampleCount": self.sample_count,
            "modelVersion": self.model_version,
            "horizonDays": self.horizon_days,
            "averageRealizedReturn": self.average_realized_return,
            "averageExcessReturn": self.average_excess_return,
            "directionalSampleCount": self.directional_sample_count,
            "directionalSuccessCount": self.directional_success_count,
            "directionalAccuracy": self.directional_accuracy,
            "byAction": {key: dict(value) for key, value in self.by_action.items()},
            "convictionBuckets": [dict(bucket) for bucket in self.conviction_buckets],
            "holdAccuracyStatus": "not_defined_without_validated_tolerance_band",
            "benchmarkPolicy": (
                "excess_return_requires_persisted_frozen_benchmark_provenance; "
                "legacy_scalar_excess_is_excluded"
            ),
            "warning": (
                "La precisión direccional sólo se calcula para buy, sell y reduce. "
                "Hold se excluye hasta definir una banda de neutralidad validada."
            ),
        }


class RecommendationPerformanceService:
    _ACTIONS = ("buy", "hold", "reduce", "sell")
    _DIRECTIONAL_ACTIONS = frozenset({"buy", "reduce", "sell"})
    _CONVICTION_BUCKETS = (
        (0.0, 0.5, "low"),
        (0.5, 0.7, "medium"),
        (0.7, 0.85, "high"),
        (0.85, 1.0000001, "very_high"),
    )

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._history = RecommendationHistoryRepository(database=self._database)

    def get_report(
        self,
        *,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> RecommendationPerformanceReport:
        # This also performs the additive outcome-schema migration before we query
        # benchmark_evidence_json on long-lived local SQLite databases.
        self._history.initialize()
        if horizon_days is not None and horizon_days <= 0:
            raise ValueError("horizon_days debe ser mayor que 0.")

        clauses: list[str] = []
        params: list[object] = []
        if model_version is not None:
            normalized_version = str(model_version).strip()
            if not normalized_version:
                raise ValueError("model_version no puede estar vacío.")
            clauses.append("r.model_version = ?")
            params.append(normalized_version)
            model_version = normalized_version
        if horizon_days is not None:
            clauses.append("o.horizon_days = ?")
            params.append(int(horizon_days))

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    r.action,
                    r.conviction,
                    r.model_version,
                    r.benchmark_symbol,
                    o.horizon_days,
                    o.realized_return,
                    o.benchmark_return,
                    o.excess_return,
                    o.benchmark_evidence_json
                FROM athena_recommendation_outcomes o
                JOIN athena_recommendations r ON r.id = o.recommendation_id
                {where}
                ORDER BY o.id
                """,
                tuple(params),
            ).fetchall()

        observations = [dict(row) for row in rows]
        for row in observations:
            row["benchmark_provenanced"] = self._has_benchmark_provenance(row)
        realized = [float(row["realized_return"]) for row in observations]
        excess = [
            float(row["excess_return"])
            for row in observations
            if row["excess_return"] is not None and row["benchmark_provenanced"]
        ]

        by_action = {
            action: self._action_metrics(
                [row for row in observations if row["action"] == action],
                action,
            )
            for action in self._ACTIONS
        }

        directional_rows = [
            row
            for row in observations
            if str(row["action"]) in self._DIRECTIONAL_ACTIONS
        ]
        directional_successes = sum(
            1 for row in directional_rows if self._is_directional_success(row)
        )
        directional_accuracy = (
            directional_successes / len(directional_rows)
            if directional_rows
            else None
        )

        buckets: list[dict[str, Any]] = []
        for low, high, label in self._CONVICTION_BUCKETS:
            bucket_rows = [
                row
                for row in directional_rows
                if low <= float(row["conviction"]) < high
            ]
            successes = sum(
                1 for row in bucket_rows if self._is_directional_success(row)
            )
            buckets.append(
                {
                    "label": label,
                    "minConviction": low,
                    "maxConvictionExclusive": min(high, 1.0),
                    "sampleCount": len(bucket_rows),
                    "successCount": successes,
                    "directionalAccuracy": (
                        successes / len(bucket_rows) if bucket_rows else None
                    ),
                    "averageConviction": (
                        mean(float(row["conviction"]) for row in bucket_rows)
                        if bucket_rows
                        else None
                    ),
                }
            )

        return RecommendationPerformanceReport(
            sample_count=len(observations),
            model_version=model_version,
            horizon_days=horizon_days,
            average_realized_return=mean(realized) if realized else None,
            average_excess_return=mean(excess) if excess else None,
            directional_sample_count=len(directional_rows),
            directional_success_count=directional_successes,
            directional_accuracy=directional_accuracy,
            by_action=by_action,
            conviction_buckets=tuple(buckets),
        )

    def _action_metrics(
        self,
        rows: list[dict[str, Any]],
        action: str,
    ) -> dict[str, Any]:
        realized = [float(row["realized_return"]) for row in rows]
        excess = [
            float(row["excess_return"])
            for row in rows
            if row["excess_return"] is not None and row.get("benchmark_provenanced") is True
        ]
        directional_accuracy: float | None = None
        success_count: int | None = None
        if action in self._DIRECTIONAL_ACTIONS:
            success_count = sum(1 for row in rows if self._is_directional_success(row))
            directional_accuracy = success_count / len(rows) if rows else None

        return {
            "sampleCount": len(rows),
            "averageRealizedReturn": mean(realized) if realized else None,
            "averageExcessReturn": mean(excess) if excess else None,
            "directionalSuccessCount": success_count,
            "directionalAccuracy": directional_accuracy,
        }

    def _has_benchmark_provenance(self, row: dict[str, Any]) -> bool:
        if row.get("benchmark_return") is None or row.get("excess_return") is None:
            return False
        raw = row.get("benchmark_evidence_json")
        if raw is None:
            return False
        try:
            evidence = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(evidence, dict) or evidence.get("status") != "resolved":
            return False
        frozen_symbol = str(row.get("benchmark_symbol") or "").strip().upper()
        evidence_symbol = str(evidence.get("benchmarkSymbol") or "").strip().upper()
        return bool(
            frozen_symbol
            and frozen_symbol == evidence_symbol
            and evidence.get("benchmarkInstrumentId") is not None
            and evidence.get("entryObservedAt")
            and evidence.get("exitObservedAt")
            and evidence.get("entryRetrievedAt")
            and evidence.get("exitRetrievedAt")
            and evidence.get("entrySourceProvider")
            and evidence.get("exitSourceProvider")
        )

    def _is_directional_success(self, row: dict[str, Any]) -> bool:
        action = str(row["action"])
        realized_return = float(row["realized_return"])
        if action == "buy":
            return realized_return > 0
        if action in {"sell", "reduce"}:
            return realized_return < 0
        raise ValueError(f"Acción no direccional: {action}")
