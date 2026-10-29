from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from datetime import date, datetime, time, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService
from app.services.market_observation_backfill_service import (
    MarketObservationBackfillReport,
    MarketObservationBackfillService,
    MarketHistoryProvider,
    ProgressCallback,
    TodayProvider,
    FROZEN_INSTRUMENT_IDENTITY_FIELDS,
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
        # History acceptance uses UTC cutoffs, never the host's local calendar day.
        self._today_provider = (
            today_provider
            if today_provider is not None
            else lambda: datetime.now(timezone.utc).date()
        )
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
        _instrument_ids: tuple[int, ...] | None = None,
        _expected_symbols: tuple[str, ...] | None = None,
        _expected_identities: tuple[tuple[Any, ...], ...] | None = None,
    ) -> VerifiedMarketHistoryBackfillReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        verification_cutoff = datetime.combine(self._today_provider(), time.max, tzinfo=timezone.utc)
        blockers_before = self._blocking_count(verification_cutoff)
        current_blockers_before = self._current_blocking_count(verification_cutoff)
        backfill = self._backfill.run(
            limit=limit,
            offset=offset,
            from_date=from_date,
            to_date=to_date,
            blocking_only=True,
            _instrument_ids=_instrument_ids,
            _expected_symbols=_expected_symbols,
            _expected_identities=_expected_identities,
        )
        blockers_after = self._blocking_count(verification_cutoff)
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


    def run_sweep(
        self,
        *,
        limit: int,
        max_batches: int = 20,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Attempt a bounded, frozen list of blockers exactly once each.

        A live blockers queue shrinks and can reorder when observations are
        persisted. Offset pagination during writes can skip instruments or
        retry the wrong ones; freeze IDs before making provider requests.
        """
        if type(limit) is not int or limit <= 0 or limit > 500:
            raise ValueError("limit debe estar entre 1 y 500.")
        if type(max_batches) is not int or max_batches <= 0:
            raise ValueError("max_batches debe ser un entero positivo.")
        # A bounded sweep may cover more than one diagnostic page. The
        # per-page SQL limit is not a cap on the eligible market universe.
        if max_batches > 1000:
            raise ValueError("max_batches no puede superar 1000 lotes.")
        max_items = limit * max_batches

        # The first sweep may run against a newly provisioned SQLite path.
        # Match run() initialization before querying the frozen blocker list.
        self._database.initialize()
        sweep_day = self._today_provider()
        cutoff = datetime.combine(sweep_day, time.max, tzinfo=timezone.utc)
        # Freeze the worklist from ONE consistent SQLite backup, not from
        # successive live queries. A concurrent ingestion or universe refresh
        # can reorder an offset-paginated blocker queue without changing its
        # total count, silently skipping instruments.
        with tempfile.TemporaryDirectory(prefix="athena-backfill-worklist-") as directory:
            frozen_path = Path(directory) / "frozen-worklist.db"
            source_path = self._database.database_path.resolve()
            with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(frozen_path)) as destination:
                    source.backup(destination)
            with closing(sqlite3.connect(frozen_path)) as frozen_connection:
                integrity = frozen_connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise RuntimeError("La copia de la cola histórica no supera la integridad SQLite.")
            frozen_database = AthenaDatabase(frozen_path)
            frozen_database.initialize()
            gap_service = MarketHistoryGapService(database=frozen_database)
            initial = gap_service.get_report(
                as_of=cutoff,
                limit=min(max_items, MarketHistoryGapService.MAX_LIMIT),
                offset=0,
            )
            frozen = list(initial.items)
            target_count = min(initial.total_blocking_count, max_items)
            while len(frozen) < target_count:
                page = gap_service.get_report(
                    as_of=cutoff,
                    limit=min(MarketHistoryGapService.MAX_LIMIT, target_count - len(frozen)),
                    offset=len(frozen),
                )
                if (
                    page.total_blocking_count != initial.total_blocking_count
                    or page.as_of != initial.as_of
                    or page.minimum_history_days != initial.minimum_history_days
                    or page.maximum_source_gap_days != initial.maximum_source_gap_days
                    or not page.items
                ):
                    raise RuntimeError(
                        "La lista de bloqueos cambió durante la congelación del barrido."
                    )
                frozen.extend(page.items)
            # Freeze every identity field from the SAME SQLite generation as
            # the blocker list. Later live catalogue changes must not silently
            # rebind observations to a different listing with the same ticker.
            frozen_repository = InstrumentRepository(database=frozen_database)
            frozen_identities: list[tuple[Any, ...]] = []
            for item in frozen:
                frozen_row = frozen_repository.get_by_id(item.instrument_id)
                if (
                    frozen_row is None
                    or not bool(frozen_row.get("is_active"))
                    or str(frozen_row.get("symbol") or "").strip().upper() != item.symbol
                ):
                    raise RuntimeError("La identidad congelada del instrumento cambió.")
                frozen_identities.append(tuple(
                    frozen_row.get(field) for field in FROZEN_INSTRUMENT_IDENTITY_FIELDS
                ))
        instrument_ids = tuple(item.instrument_id for item in frozen)
        frozen_symbols = tuple(item.symbol for item in frozen)
        if len(instrument_ids) != len(set(instrument_ids)):
            raise RuntimeError("La lista inicial de bloqueos contiene IDs duplicados.")

        reports: list[VerifiedMarketHistoryBackfillReport] = []
        for index in range(0, len(instrument_ids), limit):
            if self._today_provider() != sweep_day:
                raise RuntimeError("El corte UTC cambió durante el barrido histórico.")
            batch = instrument_ids[index:index + limit]
            reports.append(self.run(
                limit=len(batch),
                offset=0,
                from_date=from_date,
                to_date=to_date,
                _instrument_ids=batch,
                _expected_symbols=frozen_symbols[index:index + limit],
                _expected_identities=tuple(frozen_identities[index:index + limit]),
            ))
        # An empty frozen worklist must NEVER fall back to run() against the
        # live queue: a newly added instrument could then be fetched/written
        # despite not belonging to the authorized frozen selection, while the
        # report incorrectly claims zero attempted instruments.
        if self._today_provider() != sweep_day:
            raise RuntimeError("El corte UTC cambió durante el barrido histórico.")
        if reports:
            remaining_blockers = reports[-1].blockers_after
            depth_ready = reports[-1].history_ready
        else:
            coverage = MarketObservationCoverageService(
                database=self._database
            ).get_report(as_of=cutoff)
            remaining_blockers = self._blocking_count(cutoff)
            depth_ready = (
                coverage.history_eligible_instrument_count > 0
                and remaining_blockers == 0
                and coverage.current_deep_history_instrument_count
                == coverage.history_eligible_instrument_count
                and coverage.current_history_depth_ready
            )

        unattempted = max(0, initial.total_blocking_count - len(instrument_ids))
        history_ready = (
            unattempted == 0
            and depth_ready
            and all(report.backfill.failed_count == 0 for report in reports)
        )
        return {
            "status": (
                "history_criteria_satisfied"
                if history_ready else "history_criteria_still_blocked"
            ),
            "historyReady": history_ready,
            "asOf": cutoff.isoformat(),
            "initialBlockingCount": initial.total_blocking_count,
            "attemptedInstrumentCount": len(instrument_ids),
            "unattemptedInstrumentCount": unattempted,
            "remainingBlockingCount": remaining_blockers,
            "batchCount": len(reports),
            "completeWorklistProcessed": unattempted == 0,
            "batches": [report.to_api_dict() for report in reports],
            "policy": {
                "providerStitchingAllowed": False,
                "productionEvidenceClaimed": False,
                "automaticReadinessPromotion": False,
                "automaticTrading": False,
            },
            "warning": (
                "El barrido usa una lista inicial fija para no saltar bloqueos "
                "cuando cambia su orden. No demuestra origen productivo, "
                "acuerdo independiente de corporate actions ni evidencia OOS."
            ),
        }

    def _blocking_count(self, cutoff: datetime) -> int:
        return MarketHistoryGapService(database=self._database).get_report(
            limit=1, offset=0, as_of=cutoff
        ).total_blocking_count

    def _current_blocking_count(self, cutoff: datetime) -> int:
        report = MarketObservationCoverageService(database=self._database).get_report(as_of=cutoff)
        return max(0, report.history_eligible_instrument_count - report.current_deep_history_instrument_count)
