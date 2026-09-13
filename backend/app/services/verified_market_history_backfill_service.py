from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_backfill_service import (
    MarketObservationBackfillReport,
    MarketObservationBackfillService,
    MarketHistoryProvider,
    ProgressCallback,
    TodayProvider,
)


@dataclass(frozen=True)
class VerifiedMarketHistoryBackfillReport:
    backfill: MarketObservationBackfillReport
    blockers_before: int
    blockers_after: int

    @property
    def net_blockers_resolved(self) -> int:
        return max(0, self.blockers_before - self.blockers_after)

    @property
    def history_ready(self) -> bool:
        return self.blockers_after == 0 and self.backfill.failed_count == 0

    def to_api_dict(self) -> dict[str, Any]:
        backfill_payload = self.backfill.to_api_dict()
        return {
            "status": (
                "history_criteria_satisfied"
                if self.history_ready
                else "history_criteria_still_blocked"
            ),
            "backfill": backfill_payload,
            "verification": {
                "blockersBefore": self.blockers_before,
                "blockersAfter": self.blockers_after,
                "netBlockersResolved": self.net_blockers_resolved,
                "deepHistoryCriterionSatisfied": self.history_ready,
                "minimumHistoryDays": 365,
                "maximumSourceGapDays": 7,
                "providerStitchingAllowed": False,
            },
            "policy": {
                "productionEvidenceClaimed": False,
                "automaticReadinessPromotion": False,
                "automaticTrading": False,
                "humanReviewBypassed": False,
            },
            "warning": (
                "La verificación posterior evalúa únicamente observaciones persistidas. "
                "Un resultado verde en pruebas o con fixtures no constituye evidencia de "
                "cobertura operativa real del universo de producción."
            ),
        }


class VerifiedMarketHistoryBackfillService:
    """Execute blocker-only Yahoo history backfill and re-check the hard criterion.

    The service deliberately separates persistence from readiness: receiving or storing
    rows is not success unless the persisted database no longer contains a >=365-day
    history blocker under the same-provider / <=7-day-gap policy.
    """

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: MarketHistoryProvider | None = None,
        progress_callback: ProgressCallback | None = None,
        today_provider: TodayProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._backfill = MarketObservationBackfillService(
            database=self._database,
            history_provider=history_provider,
            progress_callback=progress_callback,
            today_provider=today_provider,
        )

    def run(
        self,
        *,
        limit: int,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> VerifiedMarketHistoryBackfillReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        blockers_before = self._blocking_count()
        backfill = self._backfill.run(
            limit=limit,
            offset=offset,
            from_date=from_date,
            to_date=to_date,
            blocking_only=True,
        )
        blockers_after = self._blocking_count()

        return VerifiedMarketHistoryBackfillReport(
            backfill=backfill,
            blockers_before=blockers_before,
            blockers_after=blockers_after,
        )

    def _blocking_count(self) -> int:
        return MarketHistoryGapService(database=self._database).get_report(
            limit=1,
            offset=0,
        ).total_blocking_count
