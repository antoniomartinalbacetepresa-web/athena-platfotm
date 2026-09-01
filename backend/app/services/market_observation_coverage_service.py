from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class MarketObservationCoverageReport:
    active_instrument_count: int
    covered_instrument_count: int
    observation_count: int
    earliest_observed_at: str | None
    latest_observed_at: str | None
    by_source: dict[str, dict[str, int | str | None]]

    @property
    def instrument_coverage(self) -> float:
        if self.active_instrument_count <= 0:
            return 0.0
        return self.covered_instrument_count / self.active_instrument_count

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "activeInstrumentCount": self.active_instrument_count,
            "coveredInstrumentCount": self.covered_instrument_count,
            "instrumentCoverage": self.instrument_coverage,
            "observationCount": self.observation_count,
            "earliestObservedAt": self.earliest_observed_at,
            "latestObservedAt": self.latest_observed_at,
            "bySource": {
                key: dict(value)
                for key, value in sorted(self.by_source.items())
            },
            "warning": (
                "La cobertura de instrumentos no implica todavía profundidad "
                "temporal suficiente para todos los horizontes de evaluación."
            ),
        }


class MarketObservationCoverageService:
    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

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
                """
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
            covered_instrument_count=int(
                overall["covered_instrument_count"] if overall else 0
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
        )
