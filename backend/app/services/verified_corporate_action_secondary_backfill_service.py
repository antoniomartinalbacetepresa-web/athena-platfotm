from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_coverage_service import CorporateActionCoverageService
from app.services.corporate_action_ingestion_service import CorporateActionIngestionService
from app.services.corporate_action_reconciliation_worklist_service import (
    CorporateActionReconciliationWorklistService,
)


class CorporateActionHistoryProvider(Protocol):
    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]: ...


Clock = Callable[[], datetime]
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class VerifiedCorporateActionSecondaryBackfillReport:
    as_of: datetime
    verification_as_of: datetime
    selected_event_count: int
    selected_instrument_count: int
    processed_instrument_count: int
    persisted_instrument_count: int
    no_action_count: int
    failed_count: int
    actions_received: int
    actions_inserted: int
    actions_unchanged: int
    incomplete_before: int
    incomplete_after: int
    selected_events_still_incomplete: int
    agreed_before: int
    agreed_after: int
    conflicts_before: int
    conflicts_after: int
    failures: tuple[dict[str, str], ...]
    effective_from_date: str | None
    effective_to_date: str | None

    @property
    def net_incomplete_reduced(self) -> int:
        return max(0, self.incomplete_before - self.incomplete_after)

    @property
    def status(self) -> str:
        if self.failed_count:
            return "completed_with_failures"
        if self.selected_event_count == 0:
            return "no_reconciliation_work"
        if self.selected_events_still_incomplete:
            return "targeted_events_still_incomplete"
        if self.conflicts_after > self.conflicts_before:
            return "targeted_secondary_conflict_detected"
        return "targeted_secondary_family_observed"

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": "alpha_vantage",
            "asOf": self.as_of.astimezone(timezone.utc).isoformat(),
            "verificationAsOf": self.verification_as_of.astimezone(timezone.utc).isoformat(),
            "selectedEventCount": self.selected_event_count,
            "selectedInstrumentCount": self.selected_instrument_count,
            "processedInstrumentCount": self.processed_instrument_count,
            "persistedInstrumentCount": self.persisted_instrument_count,
            "noActionCount": self.no_action_count,
            "failedCount": self.failed_count,
            "actions": {
                "received": self.actions_received,
                "inserted": self.actions_inserted,
                "unchanged": self.actions_unchanged,
            },
            "reconciliation": {
                "incompleteBefore": self.incomplete_before,
                "incompleteAfter": self.incomplete_after,
                "netIncompleteReduced": self.net_incomplete_reduced,
                "selectedEventsStillIncomplete": self.selected_events_still_incomplete,
                "agreedBefore": self.agreed_before,
                "agreedAfter": self.agreed_after,
                "conflictsBefore": self.conflicts_before,
                "conflictsAfter": self.conflicts_after,
            },
            "historyWindow": {
                "fromDate": self.effective_from_date,
                "toDate": self.effective_to_date,
            },
            "failures": [dict(item) for item in self.failures],
            "policy": {
                "minimumIndependentProviderFamilies": 2,
                "automaticCanonicalization": False,
                "productionIndependenceClaimed": False,
                "automaticReadinessPromotion": False,
                "automaticTrading": False,
            },
            "warning": (
                "La reducción de eventos incompletos demuestra únicamente evidencia técnica "
                "persistida entre familias configuradas. No demuestra independencia contractual "
                "u operativa de producción y los conflictos nunca se canonicalizan automáticamente."
            ),
        }


class VerifiedCorporateActionSecondaryBackfillService:
    """Backfill only unresolved PIT corporate-action work, then re-measure it."""

    _LOOKBACK_MARGIN_DAYS = 7

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: CorporateActionHistoryProvider,
        clock: Clock | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)
        self._history_provider = history_provider
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._progress_callback = progress_callback

    def run(
        self,
        *,
        as_of: datetime,
        limit: int = 25,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> VerifiedCorporateActionSecondaryBackfillReport:
        cutoff = self._aware_utc(as_of, "as_of")
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        worklist_service = CorporateActionReconciliationWorklistService(self._database)
        coverage_service = CorporateActionCoverageService(self._database)
        before_worklist = worklist_service.get_worklist(
            as_of=cutoff,
            limit=limit,
            offset=offset,
        )
        before_coverage = coverage_service.get_report(as_of=cutoff)
        selected_items = tuple(
            item
            for item in before_worklist.items
            if item.suggested_provider == "alpha_vantage"
        )
        selected_event_keys = {
            (item.instrument_id, item.action_type, item.effective_at)
            for item in selected_items
        }
        instrument_ids = tuple(dict.fromkeys(item.instrument_id for item in selected_items))
        effective_from, effective_to = self._resolve_window(
            selected_items=selected_items,
            as_of=cutoff,
            from_date=from_date,
            to_date=to_date,
        )

        persisted = 0
        no_action = 0
        failed = 0
        received = 0
        inserted = 0
        unchanged = 0
        failures: list[dict[str, str]] = []
        ingestion = CorporateActionIngestionService(
            market_provider=self._history_provider,
            repository=self._repository,
        )

        for index, instrument_id in enumerate(instrument_ids, start=1):
            row = self._instrument(instrument_id)
            if row is None:
                failed += 1
                failures.append(
                    {"instrumentId": str(instrument_id), "symbol": "", "error": "instrument_not_found"}
                )
                continue
            symbol = str(row["symbol"] or "").strip().upper()
            currency_raw = row["currency"]
            currency = str(currency_raw).strip().upper() if currency_raw is not None else None
            try:
                stats = ingestion.ingest_history(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    from_date=effective_from,
                    to_date=effective_to,
                    dividend_currency=currency,
                )
                received += stats.actions_received
                inserted += stats.inserted
                unchanged += stats.unchanged
                if stats.actions_received:
                    persisted += 1
                    status = "persisted"
                else:
                    no_action += 1
                    status = "no_actions"
                self._emit(index, len(instrument_ids), symbol, status, stats.actions_received)
            except Exception as exc:
                failed += 1
                failures.append(
                    {"instrumentId": str(instrument_id), "symbol": symbol, "error": str(exc)}
                )
                self._emit(index, len(instrument_ids), symbol, "failed", 0)

        verification_cutoff = self._aware_utc(self._clock(), "clock")
        if verification_cutoff < cutoff:
            verification_cutoff = cutoff
        after_worklist = worklist_service.get_worklist(
            as_of=verification_cutoff,
            limit=max(1, before_worklist.total_incomplete_event_count + len(selected_items) + 100),
            offset=0,
        )
        after_coverage = coverage_service.get_report(as_of=verification_cutoff)
        remaining_keys = {
            (item.instrument_id, item.action_type, item.effective_at)
            for item in after_worklist.items
        }
        selected_remaining = len(selected_event_keys & remaining_keys)

        return VerifiedCorporateActionSecondaryBackfillReport(
            as_of=cutoff,
            verification_as_of=verification_cutoff,
            selected_event_count=len(selected_items),
            selected_instrument_count=len(instrument_ids),
            processed_instrument_count=len(instrument_ids),
            persisted_instrument_count=persisted,
            no_action_count=no_action,
            failed_count=failed,
            actions_received=received,
            actions_inserted=inserted,
            actions_unchanged=unchanged,
            incomplete_before=before_coverage.incomplete_event_count,
            incomplete_after=after_coverage.incomplete_event_count,
            selected_events_still_incomplete=selected_remaining,
            agreed_before=before_coverage.agreed_event_count,
            agreed_after=after_coverage.agreed_event_count,
            conflicts_before=before_coverage.conflict_event_count,
            conflicts_after=after_coverage.conflict_event_count,
            failures=tuple(failures),
            effective_from_date=effective_from,
            effective_to_date=effective_to,
        )

    def _resolve_window(
        self,
        *,
        selected_items: tuple[Any, ...],
        as_of: datetime,
        from_date: str | None,
        to_date: str | None,
    ) -> tuple[str | None, str | None]:
        if from_date is not None:
            return from_date, to_date
        if not selected_items:
            return None, to_date
        earliest = min(datetime.fromisoformat(item.effective_at) for item in selected_items)
        start = earliest.astimezone(timezone.utc).date() - timedelta(days=self._LOOKBACK_MARGIN_DAYS)
        end = as_of.date() if to_date is None else datetime.fromisoformat(to_date).date()
        if start > end:
            raise ValueError("La ventana de reconciliación no puede empezar después de terminar.")
        return start.isoformat(), end.isoformat()

    def _instrument(self, instrument_id: int) -> Any | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT id, symbol, currency
                FROM instruments
                WHERE id = ? AND is_active = 1
                """,
                (instrument_id,),
            ).fetchone()

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _emit(self, index: int, total: int, symbol: str, status: str, actions: int) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(
            {
                "index": index,
                "total": total,
                "symbol": symbol,
                "status": status,
                "actions": actions,
            }
        )
