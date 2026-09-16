from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService
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
    current_blockers_before: int
    current_blockers_after: int
    eligible_instrument_count: int

    @property
    def net_blockers_resolved(self) -> int:
        return max(0, self.blockers_before - self.blockers_after)

    @property
    def net_current_blockers_resolved(self) -> int:
        return max(0, self.current_blockers_before - self.current_blockers_after)

    @property
    def history_ready(self) -> bool:
        return (
            self.eligible_instrument_count > 0
            and self.blockers_after == 0
            and self.current_blockers_after == 0
            and self.backfill.failed_count == 0
        )

    def to_api_dict(self) -> dict[str, Any]:
        backfill_payload = self.backfill.to_api_dict()
        return {
            "status": "history_criteria_satisfied" if self.history_ready else "history_criteria_still_blocked",
            "backfill": backfill_payload,
            "verification": {
                "eligibleInstrumentCount": self.eligible_instrument_count,
                "nonEmptyEligibleUniverseRequired": True,
                "blockersBefore": self.blockers_before,
                "blockersAfter": self.blockers_after,
                "netBlockersResolved": self.net_blockers_resolved,
                "currentBlockersBefore": self.current_blockers_before,
                "currentBlockersAfter": self.current_blockers_after,
                "netCurrentBlockersResolved": self.net_current_blockers_resolved,
                "deepHistoryCriterionSatisfied": self.history_ready,
                "currentDepthRequired": True,
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
                "La verificación posterior evalúa únicamente observaciones persistidas, exige "
                "un universo elegible no vacío y requiere que el tramo continuo de 365 días "
                "alcance el corte actual dentro del máximo de 7 días. Un resultado verde en "
                "pruebas o con fixtures no constituye evidencia de cobertura operativa real "
                "del universo de producción."
            ),
        }


class VerifiedMarketHistoryBackfillService:
    """Backfill blockers and verify continuous, current >=365-day history."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: MarketHistoryProvider | None = None,
        progress_callback: ProgressCallback | None = None,
        today_provider: TodayProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._today_provider = today_provider if today_provider is not None else date.today
        self._backfill = MarketObservationBackfillService(
            database=self._database,
            history_provider=history_provider,
            progress_callback=progress_callback,
            today_provider=self._today_provider,
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
        verification_cutoff = datetime.combine(self._today_provider(), time.max, tzinfo=timezone.utc)
        blockers_before = self._blocking_count()
        current_blockers_before = self._current_blocking_count(verification_cutoff)
        backfill = self._backfill.run(
            limit=limit,
            offset=offset,
            from_date=from_date,
            to_date=to_date,
            blocking_only=True,
        )
        blockers_after = self._blocking_count()
        coverage_after = MarketObservationCoverageService(database=self._database).get_report(
            as_of=verification_cutoff,
        )
        current_blockers_after = max(
            0,
            coverage_after.history_eligible_instrument_count
            - coverage_after.current_deep_history_instrument_count,
        )

        return VerifiedMarketHistoryBackfillReport(
            backfill=backfill,
            blockers_before=blockers_before,
            blockers_after=blockers_after,
            current_blockers_before=current_blockers_before,
            current_blockers_after=current_blockers_after,
            eligible_instrument_count=coverage_after.history_eligible_instrument_count,
        )

    def _blocking_count(self) -> int:
        return MarketHistoryGapService(database=self._database).get_report(limit=1, offset=0).total_blocking_count

    def _current_blocking_count(self, cutoff: datetime) -> int:
        report = MarketObservationCoverageService(database=self._database).get_report(as_of=cutoff)
        return max(0, report.history_eligible_instrument_count - report.current_deep_history_instrument_count)
