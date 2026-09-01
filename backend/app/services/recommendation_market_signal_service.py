from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from statistics import stdev
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class RecommendationMarketSignal:
    status: str
    symbol: str
    instrument_id: int | None
    as_of: str
    observation_count: int
    latest_observed_at: str | None
    latest_price: float | None
    return_20d: float | None
    return_60d: float | None
    annualized_volatility: float | None
    max_drawdown_60d: float | None
    technical_score: float | None
    risk_score: float | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "observationCount": self.observation_count,
            "latestObservedAt": self.latest_observed_at,
            "latestPrice": self.latest_price,
            "return20d": self.return_20d,
            "return60d": self.return_60d,
            "annualizedVolatility": self.annualized_volatility,
            "maxDrawdown60d": self.max_drawdown_60d,
            "technicalScore": self.technical_score,
            "riskScore": self.risk_score,
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "temporal": "observed_at_and_retrieved_at_not_after_as_of",
                "price": "raw_close_first_adjusted_close_fallback",
                "duplicateObservation": "latest_retrieved_at_before_as_of",
                "calibration": "diagnostic_only_until_out_of_sample_validated",
            },
        }


class RecommendationMarketSignalService:
    """Builds point-in-time technical/risk diagnostics from persisted prices.

    The scores are deliberately NOT production-eligible recommendations. They are
    deterministic features that can later feed a calibrated recommendation model.
    `retrieved_at <= as_of` is mandatory so historical/backfilled data cannot leak
    into a signal that pretends to have existed before ATHENA actually knew it.
    """

    _MIN_OBSERVATIONS = 61

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def evaluate(self, *, symbol: str, as_of: datetime) -> RecommendationMarketSignal:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)
        self._database.initialize()

        instrument_ids = self._active_instrument_ids(normalized_symbol)
        if not instrument_ids:
            return self._empty(
                status="instrument_not_found",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                reason="No existe un instrumento activo con ese símbolo.",
            )
        if len(instrument_ids) != 1:
            return self._empty(
                status="instrument_ambiguous",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                reason="El símbolo corresponde a más de un instrumento activo.",
            )

        instrument_id = instrument_ids[0]
        observations = self._point_in_time_prices(
            instrument_id=instrument_id,
            as_of=as_of_utc,
        )
        if len(observations) < self._MIN_OBSERVATIONS:
            return RecommendationMarketSignal(
                status="insufficient_history",
                symbol=normalized_symbol,
                instrument_id=instrument_id,
                as_of=as_of_utc.isoformat(),
                observation_count=len(observations),
                latest_observed_at=(
                    str(observations[-1]["observed_at"]) if observations else None
                ),
                latest_price=(float(observations[-1]["price"]) if observations else None),
                return_20d=None,
                return_60d=None,
                annualized_volatility=None,
                max_drawdown_60d=None,
                technical_score=None,
                risk_score=None,
                production_eligible=False,
                reason=(
                    "Se requieren al menos 61 observaciones point-in-time para "
                    "calcular momentum y riesgo sin rellenar datos artificialmente."
                ),
            )

        recent = observations[-61:]
        prices = [float(item["price"]) for item in recent]
        latest_price = prices[-1]
        return_20d = (latest_price / prices[-21]) - 1.0
        return_60d = (latest_price / prices[0]) - 1.0
        daily_returns = [
            (prices[index] / prices[index - 1]) - 1.0
            for index in range(1, len(prices))
        ]
        annualized_volatility = stdev(daily_returns) * sqrt(252.0)
        max_drawdown = self._max_drawdown(prices)

        # These bounded transforms are intentionally simple and transparent.
        # They create stable features, not a calibrated buy/sell decision.
        technical_score = self._clip(
            50.0 + (return_20d * 100.0) + (return_60d * 50.0),
            0.0,
            100.0,
        )
        risk_score = self._clip(
            (annualized_volatility * 100.0) + (abs(max_drawdown) * 100.0),
            0.0,
            100.0,
        )

        return RecommendationMarketSignal(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            as_of=as_of_utc.isoformat(),
            observation_count=len(observations),
            latest_observed_at=str(recent[-1]["observed_at"]),
            latest_price=latest_price,
            return_20d=return_20d,
            return_60d=return_60d,
            annualized_volatility=annualized_volatility,
            max_drawdown_60d=max_drawdown,
            technical_score=technical_score,
            risk_score=risk_score,
            production_eligible=False,
            reason=(
                "Las señales técnicas y de riesgo están calculadas con datos "
                "point-in-time, pero aún deben calibrarse fuera de muestra junto "
                "con fundamentales, valoración y calidad de datos."
            ),
        )

    def _active_instrument_ids(self, symbol: str) -> tuple[int, ...]:
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

    def _point_in_time_prices(
        self,
        *,
        instrument_id: int,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        with self._database.connect() as connection:
            rows = connection.execute(
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
                      AND observed_at <= ?
                      AND retrieved_at <= ?
                      AND COALESCE(close, adjusted_close) IS NOT NULL
                      AND COALESCE(close, adjusted_close) > 0
                )
                SELECT observed_at, price, retrieved_at
                FROM eligible
                WHERE row_rank = 1
                ORDER BY observed_at ASC
                """,
                (instrument_id, cutoff, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]

    def _max_drawdown(self, prices: list[float]) -> float:
        peak = prices[0]
        worst = 0.0
        for price in prices:
            if price > peak:
                peak = price
            drawdown = (price / peak) - 1.0
            if drawdown < worst:
                worst = drawdown
        return worst

    def _empty(
        self,
        *,
        status: str,
        symbol: str,
        as_of: datetime,
        reason: str,
    ) -> RecommendationMarketSignal:
        return RecommendationMarketSignal(
            status=status,
            symbol=symbol,
            instrument_id=None,
            as_of=as_of.isoformat(),
            observation_count=0,
            latest_observed_at=None,
            latest_price=None,
            return_20d=None,
            return_60d=None,
            annualized_volatility=None,
            max_drawdown_60d=None,
            technical_score=None,
            risk_score=None,
            production_eligible=False,
            reason=reason,
        )

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _clip(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))
