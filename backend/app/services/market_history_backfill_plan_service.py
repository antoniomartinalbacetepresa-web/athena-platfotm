from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.market_history_gap_service import MarketHistoryGapService


@dataclass(frozen=True)
class MarketHistoryBackfillRequest:
    instrument_id: int
    symbol: str
    reason: str
    source_provider: str
    from_date: str
    to_date: str
    requested_history_days: int

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "reason": self.reason,
            "sourceProvider": self.source_provider,
            "fromDate": self.from_date,
            "toDate": self.to_date,
            "requestedHistoryDays": self.requested_history_days,
            "providerStitchingAllowed": False,
            "replaceExistingObservations": False,
        }


@dataclass(frozen=True)
class MarketHistoryBackfillPlan:
    as_of: datetime
    total_blocking_count: int
    minimum_history_days: int
    safety_margin_days: int
    maximum_source_gap_days: int
    limit: int
    offset: int
    requests: tuple[MarketHistoryBackfillRequest, ...]

    @property
    def requested_history_days(self) -> int:
        return self.minimum_history_days + self.safety_margin_days

    def to_api_dict(self) -> dict[str, Any]:
        selected = len(self.requests)
        return {
            "status": "backfill_plan_only",
            "asOf": self.as_of.astimezone(timezone.utc).isoformat(),
            "totalBlockingCount": self.total_blocking_count,
            "selectedCount": selected,
            "hasMore": self.offset + selected < self.total_blocking_count,
            "minimumHistoryDays": self.minimum_history_days,
            "safetyMarginDays": self.safety_margin_days,
            "requestedHistoryDays": self.requested_history_days,
            "maximumSourceGapDays": self.maximum_source_gap_days,
            "limit": self.limit,
            "offset": self.offset,
            "requests": [request.to_api_dict() for request in self.requests],
            "policy": {
                "primarySourceProvider": "yahoo",
                "providerStitchingAllowed": False,
                "replaceExistingObservations": False,
                "productionEvidenceClaimed": False,
                "automaticReadinessPromotion": False,
            },
            "warning": (
                "Este plan transforma huecos persistidos en solicitudes deterministas de "
                "backfill. No ejecuta red, no mezcla proveedores, no borra observaciones "
                "existentes y no convierte una solicitud o fixture en evidencia de cobertura."
            ),
        }


class MarketHistoryBackfillPlanService:
    """Build an actionable, fail-safe plan for unresolved >=365-day history gaps."""

    DEFAULT_MINIMUM_HISTORY_DAYS = 365
    DEFAULT_SAFETY_MARGIN_DAYS = 35
    DEFAULT_MAXIMUM_SOURCE_GAP_DAYS = 7
    DEFAULT_SOURCE_PROVIDER = "yahoo"

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        minimum_history_days: int = DEFAULT_MINIMUM_HISTORY_DAYS,
        safety_margin_days: int = DEFAULT_SAFETY_MARGIN_DAYS,
        maximum_source_gap_days: int = DEFAULT_MAXIMUM_SOURCE_GAP_DAYS,
    ) -> None:
        if minimum_history_days < 365:
            raise ValueError("minimum_history_days no puede ser inferior a 365.")
        if safety_margin_days < 0:
            raise ValueError("safety_margin_days no puede ser negativo.")
        if maximum_source_gap_days <= 0:
            raise ValueError("maximum_source_gap_days debe ser mayor que 0.")
        self._database = database if database is not None else AthenaDatabase()
        self._minimum_history_days = int(minimum_history_days)
        self._safety_margin_days = int(safety_margin_days)
        self._maximum_source_gap_days = int(maximum_source_gap_days)

    def get_plan(
        self,
        *,
        as_of: datetime,
        limit: int = MarketHistoryGapService.DEFAULT_LIMIT,
        offset: int = 0,
    ) -> MarketHistoryBackfillPlan:
        effective_as_of = self._aware_utc(as_of)
        gap_report = MarketHistoryGapService(
            database=self._database,
            minimum_history_days=self._minimum_history_days,
            maximum_source_gap_days=self._maximum_source_gap_days,
        ).get_report(limit=limit, offset=offset)

        requested_days = self._minimum_history_days + self._safety_margin_days
        to_date = effective_as_of.date()
        from_date = (effective_as_of - timedelta(days=requested_days)).date()
        requests = tuple(
            MarketHistoryBackfillRequest(
                instrument_id=item.instrument_id,
                symbol=item.symbol,
                reason=item.reason,
                source_provider=self.DEFAULT_SOURCE_PROVIDER,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                requested_history_days=requested_days,
            )
            for item in gap_report.items
        )

        return MarketHistoryBackfillPlan(
            as_of=effective_as_of,
            total_blocking_count=gap_report.total_blocking_count,
            minimum_history_days=self._minimum_history_days,
            safety_margin_days=self._safety_margin_days,
            maximum_source_gap_days=self._maximum_source_gap_days,
            limit=limit,
            offset=offset,
            requests=requests,
        )

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
