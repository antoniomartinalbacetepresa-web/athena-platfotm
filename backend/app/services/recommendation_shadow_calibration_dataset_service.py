from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_shadow_capture_service import (
    RecommendationShadowCaptureService,
)


@dataclass(frozen=True)
class ShadowCalibrationRow:
    snapshot_id: int
    instrument_id: int
    symbol: str
    data_cutoff_at: str
    horizon_days: int
    outcome_due_at: str
    outcome_evaluated_at: str
    realized_return: float
    benchmark_return: float | None
    excess_return: float | None
    technical_score: float | None
    risk_score: float | None
    return_20d: float | None
    return_60d: float | None
    annualized_volatility: float | None
    max_drawdown_60d: float | None
    fundamental_coverage_ratio: float | None
    revenue_growth: float | None
    net_margin: float | None
    liabilities_to_assets: float | None
    reported_annual_pe: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotId": self.snapshot_id,
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "dataCutoffAt": self.data_cutoff_at,
            "horizonDays": self.horizon_days,
            "outcomeDueAt": self.outcome_due_at,
            "outcomeEvaluatedAt": self.outcome_evaluated_at,
            "target": {
                "realizedReturn": self.realized_return,
                "benchmarkReturn": self.benchmark_return,
                "excessReturn": self.excess_return,
            },
            "features": {
                "technicalScore": self.technical_score,
                "riskScore": self.risk_score,
                "return20d": self.return_20d,
                "return60d": self.return_60d,
                "annualizedVolatility": self.annualized_volatility,
                "maxDrawdown60d": self.max_drawdown_60d,
                "fundamentalCoverageRatio": self.fundamental_coverage_ratio,
                "revenueGrowth": self.revenue_growth,
                "netMargin": self.net_margin,
                "liabilitiesToAssets": self.liabilities_to_assets,
                "reportedAnnualPe": self.reported_annual_pe,
            },
        }


class RecommendationShadowCalibrationDatasetService:
    """Build an immutable supervised dataset from matured shadow evidence.

    The service intentionally emits continuous realized/excess returns, not
    BUY/HOLD/REDUCE/SELL labels. Action thresholds and feature weights must be
    learned and validated out of sample rather than encoded by intuition.
    """

    FEATURE_SCHEMA_VERSION = RecommendationShadowCaptureService.FEATURE_SCHEMA_VERSION

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def build(
        self,
        *,
        as_of: datetime,
        horizon_days: int | None = None,
        require_benchmark: bool = False,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of)
        if horizon_days is not None and horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")
        self._database.initialize()

        query = """
            SELECT
                s.id AS snapshot_id,
                s.instrument_id,
                s.symbol,
                s.data_cutoff_at,
                s.feature_schema_version,
                s.evidence_snapshot_json,
                o.horizon_days,
                o.due_at,
                o.evaluated_at,
                o.realized_return,
                o.benchmark_return,
                o.excess_return
            FROM athena_recommendation_shadow_snapshots s
            JOIN athena_recommendation_shadow_outcomes o
              ON o.snapshot_id = s.id
            WHERE s.feature_schema_version = ?
              AND o.evaluated_at <= ?
        """
        parameters: list[Any] = [self.FEATURE_SCHEMA_VERSION, cutoff.isoformat()]
        if horizon_days is not None:
            query += " AND o.horizon_days = ?"
            parameters.append(int(horizon_days))
        if require_benchmark:
            query += " AND o.benchmark_return IS NOT NULL AND o.excess_return IS NOT NULL"
        query += " ORDER BY s.data_cutoff_at ASC, s.id ASC, o.horizon_days ASC"

        try:
            with self._database.connect() as connection:
                rows = connection.execute(query, parameters).fetchall()
        except Exception as exc:
            if "no such table: athena_recommendation_shadow" in str(exc).lower():
                rows = []
            else:
                raise

        dataset: list[dict[str, Any]] = []
        rejected_invalid_snapshot = 0
        rejected_non_finite_target = 0
        for raw in rows:
            row = dict(raw)
            try:
                snapshot = json.loads(str(row["evidence_snapshot_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                rejected_invalid_snapshot += 1
                continue
            if not isinstance(snapshot, dict):
                rejected_invalid_snapshot += 1
                continue
            if snapshot.get("productionEligible") is not False:
                rejected_invalid_snapshot += 1
                continue
            if snapshot.get("recommendationCandidateReady") is not False:
                rejected_invalid_snapshot += 1
                continue

            market = snapshot.get("market")
            fundamentals = snapshot.get("fundamentals")
            valuation = snapshot.get("valuation")
            if not all(isinstance(item, dict) for item in (market, fundamentals, valuation)):
                rejected_invalid_snapshot += 1
                continue

            ratios = fundamentals.get("ratios") if isinstance(fundamentals, dict) else None
            if ratios is None:
                ratios = {}
            if not isinstance(ratios, dict):
                rejected_invalid_snapshot += 1
                continue

            realized_return = self._required_finite_float(row.get("realized_return"))
            if realized_return is None:
                rejected_non_finite_target += 1
                continue
            benchmark_return = self._optional_float(row.get("benchmark_return"))
            excess_return = self._optional_float(row.get("excess_return"))
            if require_benchmark and (
                benchmark_return is None or excess_return is None
            ):
                rejected_non_finite_target += 1
                continue

            calibration_row = ShadowCalibrationRow(
                snapshot_id=int(row["snapshot_id"]),
                instrument_id=int(row["instrument_id"]),
                symbol=str(row["symbol"]),
                data_cutoff_at=str(row["data_cutoff_at"]),
                horizon_days=int(row["horizon_days"]),
                outcome_due_at=str(row["due_at"]),
                outcome_evaluated_at=str(row["evaluated_at"]),
                realized_return=realized_return,
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                technical_score=self._optional_float(market.get("technicalScore")),
                risk_score=self._optional_float(market.get("riskScore")),
                return_20d=self._optional_float(market.get("return20d")),
                return_60d=self._optional_float(market.get("return60d")),
                annualized_volatility=self._optional_float(
                    market.get("annualizedVolatility")
                ),
                max_drawdown_60d=self._optional_float(market.get("maxDrawdown60d")),
                fundamental_coverage_ratio=self._optional_float(
                    fundamentals.get("coverageRatio")
                ),
                revenue_growth=self._optional_float(ratios.get("revenueGrowth")),
                net_margin=self._optional_float(ratios.get("netMargin")),
                liabilities_to_assets=self._optional_float(
                    ratios.get("liabilitiesToAssets")
                ),
                reported_annual_pe=self._optional_float(
                    valuation.get("reportedAnnualPe")
                ),
            )
            dataset.append(calibration_row.to_dict())

        return {
            "status": "shadow_calibration_dataset",
            "asOf": cutoff.isoformat(),
            "featureSchemaVersion": self.FEATURE_SCHEMA_VERSION,
            "horizonDays": horizon_days,
            "requireBenchmark": require_benchmark,
            "rowCount": len(dataset),
            "rejectedInvalidSnapshotCount": rejected_invalid_snapshot,
            "rejectedNonFiniteTargetCount": rejected_non_finite_target,
            "rows": dataset,
            "advisoryStatus": "no_advice",
            "policy": {
                "targets": "continuous_realized_and_excess_returns_only",
                "actions": "not_assigned",
                "featureWeights": "not_assigned",
                "futureOutcomes": "evaluated_at_not_after_as_of",
                "outcomeTimingMetadata": "included_for_purged_chronological_splits",
                "numericIntegrity": "non_finite_values_never_enter_calibration",
                "schema": "exact_feature_schema_version_required",
                "trainingUse": "out_of_sample_validation_required_before_advice",
            },
        }

    def _required_finite_float(self, value: object) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _optional_float(self, value: object) -> float | None:
        if value is None:
            return None
        return self._required_finite_float(value)

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
