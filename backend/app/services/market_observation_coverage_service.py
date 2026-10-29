from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class MarketObservationCoverageReport:
    active_instrument_count: int
    history_eligible_instrument_count: int
    covered_instrument_count: int
    deep_history_instrument_count: int
    observation_count: int
    earliest_observed_at: str | None
    latest_observed_at: str | None
    by_source: dict[str, dict[str, int | str | None]]
    minimum_history_days: int
    minimum_deep_history_coverage: float
    maximum_source_gap_days: int = 7
    current_deep_history_instrument_count: int = 0
    as_of: str | None = None

    @property
    def instrument_coverage(self) -> float:
        if self.history_eligible_instrument_count <= 0:
            return 0.0
        return self.covered_instrument_count / self.history_eligible_instrument_count

    @property
    def deep_history_coverage(self) -> float:
        if self.history_eligible_instrument_count <= 0:
            return 0.0
        return self.deep_history_instrument_count / self.history_eligible_instrument_count

    @property
    def current_deep_history_coverage(self) -> float:
        if self.history_eligible_instrument_count <= 0:
            return 0.0
        return (
            self.current_deep_history_instrument_count
            / self.history_eligible_instrument_count
        )

    @property
    def history_depth_ready(self) -> bool:
        return (
            self.observation_count > 0
            and self.deep_history_coverage >= self.minimum_deep_history_coverage
        )

    @property
    def current_history_depth_ready(self) -> bool:
        return (
            self.observation_count > 0
            and self.current_deep_history_coverage
            >= self.minimum_deep_history_coverage
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "activeInstrumentCount": self.active_instrument_count,
            "historyEligibleInstrumentCount": self.history_eligible_instrument_count,
            "coveredInstrumentCount": self.covered_instrument_count,
            "instrumentCoverage": self.instrument_coverage,
            "deepHistoryInstrumentCount": self.deep_history_instrument_count,
            "deepHistoryCoverage": self.deep_history_coverage,
            "currentDeepHistoryInstrumentCount": self.current_deep_history_instrument_count,
            "currentDeepHistoryCoverage": self.current_deep_history_coverage,
            "minimumHistoryDays": self.minimum_history_days,
            "minimumDeepHistoryCoverage": self.minimum_deep_history_coverage,
            "maximumSourceGapDays": self.maximum_source_gap_days,
            "sourceContinuityRequired": True,
            "positiveFiniteCloseRequired": True,
            "pointInTimeCutoffApplied": self.as_of is not None,
            "asOf": self.as_of,
            "historyDepthReady": self.history_depth_ready,
            "currentHistoryDepthReady": self.current_history_depth_ready,
            "observationCount": self.observation_count,
            "earliestObservedAt": self.earliest_observed_at,
            "latestObservedAt": self.latest_observed_at,
            "bySource": {
                key: dict(value) for key, value in sorted(self.by_source.items())
            },
            "productionCoverageClaimed": False,
            "warning": (
                "historyDepthReady exige al 100% del universo elegible un mínimo operativo "
                "de 365 días dentro de un tramo continuo de una misma fuente por instrumento "
                "y rechaza huecos superiores al máximo permitido. currentHistoryDepthReady "
                "exige además que ese tramo llegue hasta el corte PIT dentro del mismo máximo "
                "de hueco. No permite fabricar profundidad combinando proveedores distintos, "
                "no implica histórico completo desde el origen y no constituye evidencia de "
                "cobertura productiva por sí solo."
            ),
        }


class MarketObservationCoverageService:
    DEFAULT_MINIMUM_HISTORY_DAYS = 365
    DEFAULT_MINIMUM_DEEP_HISTORY_COVERAGE = 1.0
    DEFAULT_MAXIMUM_SOURCE_GAP_DAYS = 7
    _EXCLUDED_TYPES = ("etf", "fund")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        minimum_history_days: int = DEFAULT_MINIMUM_HISTORY_DAYS,
        minimum_deep_history_coverage: float = DEFAULT_MINIMUM_DEEP_HISTORY_COVERAGE,
        maximum_source_gap_days: int = DEFAULT_MAXIMUM_SOURCE_GAP_DAYS,
    ) -> None:
        # Production acceptance thresholds are floors/ceilings, not optional
        # diagnostic knobs: a caller must not turn partial history into ready.
        if (
            isinstance(minimum_history_days, bool)
            or not isinstance(minimum_history_days, int)
            or minimum_history_days < self.DEFAULT_MINIMUM_HISTORY_DAYS
        ):
            raise ValueError("minimum_history_days no puede ser inferior a 365.")
        if (
            isinstance(minimum_deep_history_coverage, bool)
            or minimum_deep_history_coverage != self.DEFAULT_MINIMUM_DEEP_HISTORY_COVERAGE
        ):
            raise ValueError("minimum_deep_history_coverage debe ser 1.0.")
        if (
            isinstance(maximum_source_gap_days, bool)
            or not isinstance(maximum_source_gap_days, int)
            or not 0 < maximum_source_gap_days <= self.DEFAULT_MAXIMUM_SOURCE_GAP_DAYS
        ):
            raise ValueError("maximum_source_gap_days debe estar entre 1 y 7.")
        self._database = database if database is not None else AthenaDatabase()
        self._minimum_history_days = int(minimum_history_days)
        self._minimum_deep_history_coverage = float(minimum_deep_history_coverage)
        self._maximum_source_gap_days = int(maximum_source_gap_days)

    def get_report(self, *, as_of: datetime | None = None) -> MarketObservationCoverageReport:
        cutoff = self._aware_utc(
            as_of if as_of is not None else datetime.now(timezone.utc),
            "as_of",
        )
        cutoff_iso = cutoff.isoformat()
        self._database.initialize()
        with self._database.connect() as connection:
            active_row = connection.execute(
                "SELECT COUNT(*) AS total FROM instruments WHERE is_active = 1"
            ).fetchone()
            eligible_row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM instruments
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(instrument_type, 'unknown'))) NOT IN ('etf', 'fund')
                """
            ).fetchone()
            overall = connection.execute(
                """
                WITH eligible_observations AS (
                    SELECT mo.instrument_id, mo.observed_at
                    FROM market_observations mo
                    JOIN instruments i ON i.id = mo.instrument_id
                    WHERE i.is_active = 1
                      AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown'))) NOT IN ('etf', 'fund')
                      AND julianday(mo.observed_at) <= julianday(?)
                      AND julianday(mo.retrieved_at) <= julianday(?)
                  AND typeof(mo.close) IN ('integer', 'real')
                  AND mo.close > 0
                  AND mo.close < 1.0e308
                  AND julianday(mo.retrieved_at) >= julianday(mo.observed_at)
                  AND (mo.source_timestamp IS NULL OR julianday(mo.source_timestamp) <= julianday(mo.retrieved_at))
                  AND TRIM(COALESCE(mo.source_provider, '')) <> ''
                  AND INSTR(mo.source_provider, '%') = 0
                  AND INSTR(mo.source_provider, '&') = 0
                  AND INSTR(mo.source_provider, CHAR(0)) = 0
                  AND mo.source_provider NOT GLOB '*[^ -~]*'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%fmp%'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%financialmodelingprep%'
                )
                SELECT COUNT(*) AS observation_count,
                       COUNT(DISTINCT instrument_id) AS covered_instrument_count,
                       (SELECT observed_at FROM eligible_observations
                        ORDER BY julianday(observed_at), observed_at LIMIT 1) AS earliest_observed_at,
                       (SELECT observed_at FROM eligible_observations
                        ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT 1) AS latest_observed_at
                FROM eligible_observations
                """,
                (cutoff_iso, cutoff_iso),
            ).fetchone()

            deep_row = connection.execute(
                """
                WITH normalized_history AS (
                    SELECT mo.instrument_id,
                           CASE
                               WHEN LOWER(TRIM(mo.source_provider)) IN ('yahoo', 'yahoo_finance') THEN 'yahoo'
                               ELSE TRIM(mo.source_provider)
                           END AS source_provider,
                           mo.observed_at
                    FROM market_observations mo
                    JOIN instruments i ON i.id = mo.instrument_id
                    WHERE i.is_active = 1
                      AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown'))) NOT IN ('etf', 'fund')
                      AND julianday(mo.observed_at) <= julianday(?)
                  AND julianday(mo.retrieved_at) <= julianday(?)
                  AND typeof(mo.close) IN ('integer', 'real')
                  AND mo.close > 0
                  AND mo.close < 1.0e308
                  AND julianday(mo.retrieved_at) >= julianday(mo.observed_at)
                  AND (mo.source_timestamp IS NULL OR julianday(mo.source_timestamp) <= julianday(mo.retrieved_at))
                  AND TRIM(COALESCE(mo.source_provider, '')) <> ''
                  AND INSTR(mo.source_provider, '%') = 0
                  AND INSTR(mo.source_provider, '&') = 0
                  AND INSTR(mo.source_provider, CHAR(0)) = 0
                  AND mo.source_provider NOT GLOB '*[^ -~]*'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%fmp%'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%financialmodelingprep%'
                ),
                ordered_history AS (
                    SELECT instrument_id,
                           source_provider,
                           observed_at,
                           LAG(observed_at) OVER (
                               PARTITION BY instrument_id, source_provider
                               ORDER BY julianday(observed_at), observed_at
                           ) AS previous_observed_at
                    FROM normalized_history
                ),
                marked_history AS (
                    SELECT instrument_id,
                           source_provider,
                           observed_at,
                           CASE
                               WHEN previous_observed_at IS NULL THEN 1
                               WHEN julianday(observed_at) - julianday(previous_observed_at) > ? THEN 1
                               ELSE 0
                           END AS starts_new_segment
                    FROM ordered_history
                ),
                segmented_history AS (
                    SELECT instrument_id,
                           source_provider,
                           observed_at,
                           SUM(starts_new_segment) OVER (
                               PARTITION BY instrument_id, source_provider
                               ORDER BY julianday(observed_at), observed_at
                               ROWS UNBOUNDED PRECEDING
                           ) AS segment_id
                    FROM marked_history
                ),
                source_segments AS (
                    SELECT instrument_id,
                           source_provider,
                           segment_id,
                           MIN(observed_at) AS segment_start,
                           MAX(julianday(observed_at)) AS segment_end_jd,
                           MAX(julianday(observed_at)) - MIN(julianday(observed_at)) AS history_span_days
                    FROM segmented_history
                    GROUP BY instrument_id, source_provider, segment_id
                )
                SELECT COUNT(DISTINCT CASE
                           WHEN history_span_days >= ? THEN instrument_id
                       END) AS total,
                       COUNT(DISTINCT CASE
                           WHEN history_span_days >= ?
                            AND julianday(?) - segment_end_jd BETWEEN 0 AND ?
                           THEN instrument_id
                       END) AS current_total
                FROM source_segments
                """,
                (
                    cutoff_iso,
                    cutoff_iso,
                    self._maximum_source_gap_days,
                    self._minimum_history_days,
                    self._minimum_history_days,
                    cutoff_iso,
                    self._maximum_source_gap_days,
                ),
            ).fetchone()

            source_rows = connection.execute(
                """
                WITH normalized_history AS (
                    SELECT mo.instrument_id,
                           CASE
                               WHEN LOWER(TRIM(mo.source_provider)) IN ('yahoo', 'yahoo_finance') THEN 'yahoo'
                               ELSE TRIM(mo.source_provider)
                           END AS source_provider,
                           mo.observed_at
                    FROM market_observations mo
                    JOIN instruments i ON i.id = mo.instrument_id
                    WHERE i.is_active = 1
                      AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown'))) NOT IN ('etf', 'fund')
                      AND julianday(mo.observed_at) <= julianday(?)
                  AND julianday(mo.retrieved_at) <= julianday(?)
                  AND typeof(mo.close) IN ('integer', 'real')
                  AND mo.close > 0
                  AND mo.close < 1.0e308
                  AND julianday(mo.retrieved_at) >= julianday(mo.observed_at)
                  AND (mo.source_timestamp IS NULL OR julianday(mo.source_timestamp) <= julianday(mo.retrieved_at))
                  AND TRIM(COALESCE(mo.source_provider, '')) <> ''
                  AND INSTR(mo.source_provider, '%') = 0
                  AND INSTR(mo.source_provider, '&') = 0
                  AND INSTR(mo.source_provider, CHAR(0)) = 0
                  AND mo.source_provider NOT GLOB '*[^ -~]*'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%fmp%'
                  AND LOWER(REPLACE(REPLACE(REPLACE(mo.source_provider, '_', ''), '-', ''), ' ', '')) NOT LIKE '%financialmodelingprep%'
                )
                SELECT grouped.source_provider,
                       COUNT(*) AS observation_count,
                       COUNT(DISTINCT grouped.instrument_id) AS covered_instrument_count,
                       (SELECT nh.observed_at FROM normalized_history nh
                        WHERE nh.source_provider = grouped.source_provider
                        ORDER BY julianday(nh.observed_at), nh.observed_at LIMIT 1) AS earliest_observed_at,
                       (SELECT nh.observed_at FROM normalized_history nh
                        WHERE nh.source_provider = grouped.source_provider
                        ORDER BY julianday(nh.observed_at) DESC, nh.observed_at DESC LIMIT 1) AS latest_observed_at
                FROM normalized_history grouped
                GROUP BY grouped.source_provider
                ORDER BY grouped.source_provider
                """,
                (cutoff_iso, cutoff_iso),
            ).fetchall()

        by_source: dict[str, dict[str, int | str | None]] = {}
        for row in source_rows:
            by_source[str(row["source_provider"])] = {
                "observationCount": int(row["observation_count"]),
                "coveredInstrumentCount": int(row["covered_instrument_count"]),
                "earliestObservedAt": (
                    str(row["earliest_observed_at"])
                    if row["earliest_observed_at"] is not None
                    else None
                ),
                "latestObservedAt": (
                    str(row["latest_observed_at"])
                    if row["latest_observed_at"] is not None
                    else None
                ),
            }

        return MarketObservationCoverageReport(
            active_instrument_count=int(active_row["total"] if active_row else 0),
            history_eligible_instrument_count=int(eligible_row["total"] if eligible_row else 0),
            covered_instrument_count=int(
                overall["covered_instrument_count"] if overall else 0
            ),
            deep_history_instrument_count=int(
                deep_row["total"] if deep_row and deep_row["total"] is not None else 0
            ),
            current_deep_history_instrument_count=int(
                deep_row["current_total"]
                if deep_row and deep_row["current_total"] is not None
                else 0
            ),
            observation_count=int(overall["observation_count"] if overall else 0),
            earliest_observed_at=(
                str(overall["earliest_observed_at"])
                if overall and overall["earliest_observed_at"] is not None
                else None
            ),
            latest_observed_at=(
                str(overall["latest_observed_at"])
                if overall and overall["latest_observed_at"] is not None
                else None
            ),
            by_source=by_source,
            minimum_history_days=self._minimum_history_days,
            minimum_deep_history_coverage=self._minimum_deep_history_coverage,
            maximum_source_gap_days=self._maximum_source_gap_days,
            as_of=cutoff_iso,
        )

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
