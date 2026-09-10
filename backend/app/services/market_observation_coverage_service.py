from __future__ import annotations

from dataclasses import dataclass
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
    def history_depth_ready(self) -> bool:
        return (
            self.observation_count > 0
            and self.deep_history_coverage >= self.minimum_deep_history_coverage
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
            "minimumHistoryDays": self.minimum_history_days,
            "minimumDeepHistoryCoverage": self.minimum_deep_history_coverage,
            "historyDepthReady": self.history_depth_ready,
            "observationCount": self.observation_count,
            "earliestObservedAt": self.earliest_observed_at,
            "latestObservedAt": self.latest_observed_at,
            "bySource": {
                key: dict(value)
                for key, value in sorted(self.by_source.items())
            },
            "warning": (
                "historyDepthReady es un mínimo operativo para el horizonte "
                "actual de 365 días; no implica histórico completo desde el "
                "origen del mercado ni cobertura suficiente para todos los usos."
            ),
        }


class MarketObservationCoverageService:
    DEFAULT_MINIMUM_HISTORY_DAYS = 365
    DEFAULT_MINIMUM_DEEP_HISTORY_COVERAGE = 0.30
    _EXCLUDED_TYPES = ("etf", "fund")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        minimum_history_days: int = DEFAULT_MINIMUM_HISTORY_DAYS,
        minimum_deep_history_coverage: float = DEFAULT_MINIMUM_DEEP_HISTORY_COVERAGE,
    ) -> None:
        if minimum_history_days <= 0:
            raise ValueError("minimum_history_days debe ser mayor que 0.")
        if not 0 < minimum_deep_history_coverage <= 1:
            raise ValueError(
                "minimum_deep_history_coverage debe estar entre 0 y 1."
            )
        self._database = database if database is not None else AthenaDatabase()
        self._minimum_history_days = int(minimum_history_days)
        self._minimum_deep_history_coverage = float(
            minimum_deep_history_coverage
        )

    def get_report(self) -> MarketObservationCoverageReport:
        self._database.initialize()
        with self._database.connect() as connection:
            active_row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM instruments
                WHERE is_active = 1
                """
            ).fetchone()

            eligible_row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM instruments
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(instrument_type, 'unknown')))
                      NOT IN ('etf', 'fund')
                """
            ).fetchone()

            overall = connection.execute(
                """
                SELECT
                    COUNT(*) AS observation_count,
                    COUNT(DISTINCT mo.instrument_id) AS covered_instrument_count,
                    MIN(mo.observed_at) AS earliest_observed_at,
                    MAX(mo.observed_at) AS latest_observed_at
                FROM market_observations mo
                JOIN instruments i ON i.id = mo.instrument_id
                WHERE i.is_active = 1
                  AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown')))
                      NOT IN ('etf', 'fund')
                """
            ).fetchone()

            deep_row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM (
                    SELECT mo.instrument_id
                    FROM market_observations mo
                    JOIN instruments i ON i.id = mo.instrument_id
                    WHERE i.is_active = 1
                      AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown')))
                          NOT IN ('etf', 'fund')
                    GROUP BY mo.instrument_id
                    HAVING (
                        julianday(MAX(mo.observed_at)) -
                        julianday(MIN(mo.observed_at))
                    ) >= ?
                ) deep_history
                """,
                (self._minimum_history_days,),
            ).fetchone()

            source_rows = connection.execute(
                """
                SELECT
                    mo.source_provider,
                    COUNT(*) AS observation_count,
                    COUNT(DISTINCT mo.instrument_id) AS covered_instrument_count,
                    MIN(mo.observed_at) AS earliest_observed_at,
                    MAX(mo.observed_at) AS latest_observed_at
                FROM market_observations mo
                JOIN instruments i ON i.id = mo.instrument_id
                WHERE i.is_active = 1
                  AND LOWER(TRIM(COALESCE(i.instrument_type, 'unknown')))
                      NOT IN ('etf', 'fund')
                GROUP BY mo.source_provider
                ORDER BY mo.source_provider
                """
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
            history_eligible_instrument_count=int(
                eligible_row["total"] if eligible_row else 0
            ),
            covered_instrument_count=int(
                overall["covered_instrument_count"] if overall else 0
            ),
            deep_history_instrument_count=int(
                deep_row["total"] if deep_row else 0
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
        )
