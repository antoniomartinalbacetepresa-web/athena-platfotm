from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import MarketObservationRepository


@dataclass(frozen=True)
class PortfolioCorrelationResult:
    left_instrument_id: int
    right_instrument_id: int
    source_provider: str
    knowledge_cutoff: str
    sample_count: int
    correlation: float
    first_return_date: str
    last_return_date: str
    latest_retrieved_at: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "leftInstrumentId": self.left_instrument_id,
            "rightInstrumentId": self.right_instrument_id,
            "sourceProvider": self.source_provider,
            "knowledgeCutoff": self.knowledge_cutoff,
            "sampleCount": self.sample_count,
            "correlation": self.correlation,
            "firstReturnDate": self.first_return_date,
            "lastReturnDate": self.last_return_date,
            "latestRetrievedAt": self.latest_retrieved_at,
            "priceField": "adjusted_close",
            "alignmentPolicy": "utc_calendar_date_intersection",
            "returnPolicy": "simple_return_consecutive_observations_per_instrument",
            "recommendationPolicy": "no_advice",
            "productionEligible": False,
            "allocationInfluence": False,
            "automaticTrading": False,
        }


class PortfolioCorrelationService:
    """Computes descriptive PIT correlation from verified adjusted closes only."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        observation_repository: MarketObservationRepository | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._observations = (
            observation_repository
            if observation_repository is not None
            else MarketObservationRepository(database=self._database)
        )

    def calculate_pair(
        self,
        *,
        left_instrument_id: int,
        right_instrument_id: int,
        source_provider: str,
        knowledge_cutoff: datetime,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
    ) -> PortfolioCorrelationResult:
        if left_instrument_id <= 0 or right_instrument_id <= 0:
            raise ValueError("Los instrument_id deben ser positivos.")
        if left_instrument_id == right_instrument_id:
            raise ValueError("La correlación requiere dos instrumentos distintos.")
        provider = str(source_provider or "").strip()
        if not provider:
            raise ValueError("source_provider es obligatorio.")
        cutoff = self._utc(knowledge_cutoff, "knowledge_cutoff")

        left_rows = self._observations.list_for_instrument(
            left_instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=observed_from,
            observed_to=observed_to,
        )
        right_rows = self._observations.list_for_instrument(
            right_instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=observed_from,
            observed_to=observed_to,
        )

        left_returns, left_retrieved = self._returns_by_date(left_rows, "left")
        right_returns, right_retrieved = self._returns_by_date(right_rows, "right")
        common_dates = sorted(set(left_returns).intersection(right_returns))
        if len(common_dates) < 2:
            raise ValueError(
                "La correlación requiere al menos dos rendimientos alineados verificables."
            )

        x = [left_returns[date] for date in common_dates]
        y = [right_returns[date] for date in common_dates]
        correlation = self._pearson(x, y)
        latest_retrieved = max(left_retrieved, right_retrieved)
        if latest_retrieved > cutoff:
            raise RuntimeError("Una observación posterior al knowledge_cutoff alcanzó el cálculo.")

        return PortfolioCorrelationResult(
            left_instrument_id=left_instrument_id,
            right_instrument_id=right_instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff.isoformat(),
            sample_count=len(common_dates),
            correlation=correlation,
            first_return_date=common_dates[0],
            last_return_date=common_dates[-1],
            latest_retrieved_at=latest_retrieved.isoformat(),
        )

    def _returns_by_date(
        self,
        rows: list[dict[str, Any]],
        side: str,
    ) -> tuple[dict[str, float], datetime]:
        if len(rows) < 3:
            raise ValueError(
                f"{side} necesita al menos tres observaciones para dos rendimientos."
            )

        prices: list[tuple[str, float, datetime]] = []
        seen_dates: set[str] = set()
        for row in rows:
            observed = self._parse_iso(row.get("observed_at"), f"{side}.observed_at")
            retrieved = self._parse_iso(row.get("retrieved_at"), f"{side}.retrieved_at")
            if retrieved < observed:
                raise ValueError(f"{side} contiene provenance temporal imposible.")
            date_key = observed.date().isoformat()
            if date_key in seen_dates:
                raise ValueError(
                    f"{side} contiene más de una observación para {date_key}."
                )
            seen_dates.add(date_key)

            raw_price = row.get("adjusted_close")
            if isinstance(raw_price, bool) or raw_price is None:
                raise ValueError(f"{side} requiere adjusted_close verificable.")
            price = float(raw_price)
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"{side}.adjusted_close debe ser finito y positivo.")
            prices.append((date_key, price, retrieved))

        prices.sort(key=lambda item: item[0])
        returns: dict[str, float] = {}
        latest_retrieved = prices[0][2]
        previous_price = prices[0][1]
        for date_key, price, retrieved in prices[1:]:
            value = price / previous_price - 1.0
            if not math.isfinite(value):
                raise ValueError("Se obtuvo un rendimiento no finito.")
            returns[date_key] = value
            previous_price = price
            if retrieved > latest_retrieved:
                latest_retrieved = retrieved
        return returns, latest_retrieved

    def _pearson(self, x: list[float], y: list[float]) -> float:
        if len(x) != len(y) or len(x) < 2:
            raise ValueError("Las series alineadas son insuficientes.")
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        dx = [value - mean_x for value in x]
        dy = [value - mean_y for value in y]
        variance_x = sum(value * value for value in dx)
        variance_y = sum(value * value for value in dy)
        if variance_x <= 0 or variance_y <= 0:
            raise ValueError("La correlación no está definida para una serie sin varianza.")
        covariance = sum(a * b for a, b in zip(dx, dy, strict=True))
        result = covariance / math.sqrt(variance_x * variance_y)
        if not math.isfinite(result):
            raise ValueError("La correlación resultante no es finita.")
        return max(-1.0, min(1.0, result))

    def _utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_iso(self, value: Any, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} no contiene una fecha ISO válida.") from exc
        return self._utc(parsed, field)
