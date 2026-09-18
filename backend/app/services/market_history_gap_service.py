from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class MarketHistoryGap:
    instrument_id: int
    symbol: str
    reason: str
    source_count: int
    best_source_provider: str | None
    best_history_span_days: float | None
    best_maximum_gap_days: float | None
    best_latest_observation_age_days: float | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "reason": self.reason,
            "sourceCount": self.source_count,
            "bestSourceProvider": self.best_source_provider,
            "bestHistorySpanDays": self.best_history_span_days,
            "bestMaximumGapDays": self.best_maximum_gap_days,
            "bestLatestObservationAgeDays": self.best_latest_observation_age_days,
        }


@dataclass(frozen=True)
class MarketHistoryGapReport:
    total_blocking_count: int
    no_observations_count: int
    insufficient_span_count: int
    discontinuous_source_count: int
    stale_source_count: int
    minimum_history_days: int
    maximum_source_gap_days: int
    maximum_latest_observation_age_days: int
    limit: int
    offset: int
    items: tuple[MarketHistoryGap, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "totalBlockingCount": self.total_blocking_count,
            "blockingByReason": {
                "no_observations": self.no_observations_count,
                "insufficient_span": self.insufficient_span_count,
                "discontinuous_source": self.discontinuous_source_count,
                "stale_source": self.stale_source_count,
            },
            "minimumHistoryDays": self.minimum_history_days,
            "maximumSourceGapDays": self.maximum_source_gap_days,
            "maximumLatestObservationAgeDays": self.maximum_latest_observation_age_days,
            "limit": self.limit,
            "offset": self.offset,
            "items": [item.to_api_dict() for item in self.items],
            "productionEvidenceClaimed": False,
            "warning": (
                "Este informe prioriza huecos del histórico persistido; no ejecuta "
                "backfill, no mezcla proveedores y no convierte fixtures o cobertura "
                "parcial en evidencia de producción."
            ),
        }


class MarketHistoryGapService:
    DEFAULT_MINIMUM_HISTORY_DAYS = 365
    DEFAULT_MAXIMUM_SOURCE_GAP_DAYS = 7
    DEFAULT_MAXIMUM_LATEST_OBSERVATION_AGE_DAYS = 7
    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        minimum_history_days: int = DEFAULT_MINIMUM_HISTORY_DAYS,
        maximum_source_gap_days: int = DEFAULT_MAXIMUM_SOURCE_GAP_DAYS,
        maximum_latest_observation_age_days: int = DEFAULT_MAXIMUM_LATEST_OBSERVATION_AGE_DAYS,
    ) -> None:
        if minimum_history_days < self.DEFAULT_MINIMUM_HISTORY_DAYS:
            raise ValueError(
                "minimum_history_days no puede ser inferior a "
                f"{self.DEFAULT_MINIMUM_HISTORY_DAYS}."
            )
        if maximum_source_gap_days <= 0:
            raise ValueError("maximum_source_gap_days debe ser mayor que 0.")
        if maximum_latest_observation_age_days <= 0:
            raise ValueError("maximum_latest_observation_age_days debe ser mayor que 0.")
        self._database = database if database is not None else AthenaDatabase()
        self._minimum_history_days = int(minimum_history_days)
        self._maximum_source_gap_days = int(maximum_source_gap_days)
        self._maximum_latest_observation_age_days = int(maximum_latest_observation_age_days)

    def get_report(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> MarketHistoryGapReport:
        if limit <= 0 or limit > self.MAX_LIMIT:
            raise ValueError(f"limit debe estar entre 1 y {self.MAX_LIMIT}.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        params = (
            self._maximum_source_gap_days,
            self._minimum_history_days,
            self._maximum_latest_observation_age_days,
            self._minimum_history_days,
            self._minimum_history_days,
        )
        ctes = """
            WITH eligible AS (
                SELECT id AS instrument_id, UPPER(TRIM(symbol)) AS symbol
                FROM instruments
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(instrument_type, 'unknown'))) NOT IN ('etf', 'fund')
            ),
            normalized_history AS (
                SELECT mo.instrument_id,
                       CASE
                           WHEN LOWER(TRIM(mo.source_provider)) IN ('yahoo', 'yahoo_finance') THEN 'yahoo'
                           ELSE TRIM(mo.source_provider)
                       END AS source_provider,
                       mo.observed_at
                FROM market_observations mo
                JOIN eligible e ON e.instrument_id = mo.instrument_id
            ),
            ordered_history AS (
                SELECT instrument_id,
                       source_provider,
                       observed_at,
                       LAG(observed_at) OVER (
                           PARTITION BY instrument_id, source_provider
                           ORDER BY observed_at
                       ) AS previous_observed_at
                FROM normalized_history
            ),
            marked_history AS (
                SELECT instrument_id,
                       source_provider,
                       observed_at,
                       previous_observed_at,
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
                       previous_observed_at,
                       starts_new_segment,
                       SUM(starts_new_segment) OVER (
                           PARTITION BY instrument_id, source_provider
                           ORDER BY observed_at
                           ROWS UNBOUNDED PRECEDING
                       ) AS segment_id
                FROM marked_history
            ),
            source_segments AS (
                SELECT instrument_id,
                       source_provider,
                       segment_id,
                       julianday(MAX(observed_at)) - julianday(MIN(observed_at)) AS continuous_span_days,
                       julianday('now') - julianday(MAX(observed_at)) AS latest_observation_age_days
                FROM segmented_history
                GROUP BY instrument_id, source_provider, segment_id
            ),
            source_stats AS (
                SELECT instrument_id,
                       source_provider,
                       julianday(MAX(observed_at)) - julianday(MIN(observed_at)) AS history_span_days,
                       MAX(CASE
                           WHEN previous_observed_at IS NULL THEN 0.0
                           ELSE julianday(observed_at) - julianday(previous_observed_at)
                       END) AS maximum_gap_days,
                       julianday('now') - julianday(MAX(observed_at)) AS latest_observation_age_days
                FROM ordered_history
                GROUP BY instrument_id, source_provider
            ),
            source_quality AS (
                SELECT ss.instrument_id,
                       ss.source_provider,
                       ss.history_span_days,
                       ss.maximum_gap_days,
                       ss.latest_observation_age_days,
                       COALESCE(MAX(seg.continuous_span_days), 0.0) AS best_continuous_span_days,
                       MAX(CASE
                           WHEN seg.continuous_span_days >= ?
                            AND seg.latest_observation_age_days <= ? THEN 1
                           ELSE 0
                       END) AS has_current_deep_segment
                FROM source_stats ss
                LEFT JOIN source_segments seg
                  ON seg.instrument_id = ss.instrument_id
                 AND seg.source_provider = ss.source_provider
                GROUP BY ss.instrument_id,
                         ss.source_provider,
                         ss.history_span_days,
                         ss.maximum_gap_days,
                         ss.latest_observation_age_days
            ),
            summary AS (
                SELECT instrument_id,
                       COUNT(*) AS source_count,
                       MAX(has_current_deep_segment) AS has_current_deep_source,
                       MAX(CASE WHEN history_span_days >= ? THEN 1 ELSE 0 END) AS has_long_source,
                       MIN(latest_observation_age_days) AS best_latest_observation_age_days
                FROM source_quality
                GROUP BY instrument_id
            ),
            ranked AS (
                SELECT instrument_id,
                       source_provider,
                       history_span_days,
                       maximum_gap_days,
                       latest_observation_age_days,
                       ROW_NUMBER() OVER (
                           PARTITION BY instrument_id
                           ORDER BY
                               has_current_deep_segment DESC,
                               CASE WHEN history_span_days >= ? THEN 0 ELSE 1 END,
                               best_continuous_span_days DESC,
                               latest_observation_age_days ASC,
                               history_span_days DESC,
                               source_provider ASC
                       ) AS source_rank
                FROM source_quality
            ),
            blockers AS (
                SELECT e.instrument_id,
                       e.symbol,
                       CASE
                           WHEN s.instrument_id IS NULL THEN 'no_observations'
                           WHEN s.has_current_deep_source = 1 THEN NULL
                           WHEN s.has_long_source = 0 THEN 'insufficient_span'
                           WHEN s.best_latest_observation_age_days > ? THEN 'stale_source'
                           ELSE 'discontinuous_source'
                       END AS reason,
                       COALESCE(s.source_count, 0) AS source_count,
                       r.source_provider AS best_source_provider,
                       r.history_span_days AS best_history_span_days,
                       r.maximum_gap_days AS best_maximum_gap_days,
                       r.latest_observation_age_days AS best_latest_observation_age_days
                FROM eligible e
                LEFT JOIN summary s ON s.instrument_id = e.instrument_id
                LEFT JOIN ranked r
                  ON r.instrument_id = e.instrument_id
                 AND r.source_rank = 1
            )
        """
        query_params = (*params, self._maximum_latest_observation_age_days)

        with self._database.connect() as connection:
            counts = connection.execute(
                ctes
                + """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN reason = 'no_observations' THEN 1 ELSE 0 END) AS no_observations,
                       SUM(CASE WHEN reason = 'insufficient_span' THEN 1 ELSE 0 END) AS insufficient_span,
                       SUM(CASE WHEN reason = 'discontinuous_source' THEN 1 ELSE 0 END) AS discontinuous_source,
                       SUM(CASE WHEN reason = 'stale_source' THEN 1 ELSE 0 END) AS stale_source
                FROM blockers
                WHERE reason IS NOT NULL
                """,
                query_params,
            ).fetchone()
            rows = connection.execute(
                ctes
                + """
                SELECT instrument_id,
                       symbol,
                       reason,
                       source_count,
                       best_source_provider,
                       best_history_span_days,
                       best_maximum_gap_days,
                       best_latest_observation_age_days
                FROM blockers
                WHERE reason IS NOT NULL
                ORDER BY
                    CASE reason
                        WHEN 'no_observations' THEN 0
                        WHEN 'insufficient_span' THEN 1
                        WHEN 'stale_source' THEN 2
                        ELSE 3
                    END,
                    symbol ASC,
                    instrument_id ASC
                LIMIT ? OFFSET ?
                """,
                (*query_params, limit, offset),
            ).fetchall()

        items = tuple(
            MarketHistoryGap(
                instrument_id=int(row["instrument_id"]),
                symbol=str(row["symbol"]),
                reason=str(row["reason"]),
                source_count=int(row["source_count"]),
                best_source_provider=(
                    str(row["best_source_provider"])
                    if row["best_source_provider"] is not None
                    else None
                ),
                best_history_span_days=(
                    float(row["best_history_span_days"])
                    if row["best_history_span_days"] is not None
                    else None
                ),
                best_maximum_gap_days=(
                    float(row["best_maximum_gap_days"])
                    if row["best_maximum_gap_days"] is not None
                    else None
                ),
                best_latest_observation_age_days=(
                    float(row["best_latest_observation_age_days"])
                    if row["best_latest_observation_age_days"] is not None
                    else None
                ),
            )
            for row in rows
        )
        return MarketHistoryGapReport(
            total_blocking_count=int(counts["total"] if counts else 0),
            no_observations_count=int(counts["no_observations"] or 0) if counts else 0,
            insufficient_span_count=int(counts["insufficient_span"] or 0) if counts else 0,
            discontinuous_source_count=int(counts["discontinuous_source"] or 0) if counts else 0,
            stale_source_count=int(counts["stale_source"] or 0) if counts else 0,
            minimum_history_days=self._minimum_history_days,
            maximum_source_gap_days=self._maximum_source_gap_days,
            maximum_latest_observation_age_days=self._maximum_latest_observation_age_days,
            limit=limit,
            offset=offset,
            items=items,
        )