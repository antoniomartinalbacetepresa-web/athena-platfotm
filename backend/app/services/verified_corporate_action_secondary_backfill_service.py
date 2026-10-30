from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable, Protocol

from app.database.athena_database import AthenaDatabase
from app.database.read_only_snapshot_database import ReadOnlySnapshotDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.corporate_action_coverage_service import CorporateActionCoverageService
from app.services.corporate_action_ingestion_service import CorporateActionIngestionService
from app.services.market_observation_backfill_service import FROZEN_INSTRUMENT_IDENTITY_FIELDS
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


class _ExpectedSecondaryProvider:
    """Fail closed if a secondary-backfill observation comes from another family."""

    EXPECTED_SOURCE_PROVIDER = "alpha_vantage"

    def __init__(self, delegate: CorporateActionHistoryProvider) -> None:
        self._delegate = delegate

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        rows = self._delegate.get_history(
            symbol,
            from_date=from_date,
            to_date=to_date,
        )
        verified: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(
                    "La fuente secundaria devolvió una observación no estructurada."
                )
            source = str(row.get("sourceProvider") or "").strip().lower()
            if source != self.EXPECTED_SOURCE_PROVIDER:
                raise RuntimeError(
                    "La observación del backfill secundario no pertenece a la familia "
                    f"esperada {self.EXPECTED_SOURCE_PROVIDER}."
                )
            verified.append(dict(row))
        return verified


Clock = Callable[[], datetime]
ProgressCallback = Callable[[dict[str, Any]], None]
EventKey = tuple[int, str, str]


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
    selected_events_conflicting: int
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
        if self.selected_events_conflicting:
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
                "selectedEventsConflicting": self.selected_events_conflicting,
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
                "expectedSecondaryProviderFamily": _ExpectedSecondaryProvider.EXPECTED_SOURCE_PROVIDER,
                "providerFamilyEnforced": True,
                "eventLevelConflictVerification": True,
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
        _selected_items: tuple[Any, ...] | None = None,
        _expected_identities: dict[int, tuple[Any, ...]] | None = None,
    ) -> VerifiedCorporateActionSecondaryBackfillReport:
        cutoff = self._aware_utc(as_of, "as_of")
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        worklist_service = CorporateActionReconciliationWorklistService(self._database)
        coverage_service = CorporateActionCoverageService(self._database)
        if _selected_items is None:
            before_worklist = worklist_service.get_worklist(
                as_of=cutoff, limit=limit, offset=offset,
            )
            selected_items = tuple(
                item for item in before_worklist.items
                if item.suggested_provider == "alpha_vantage"
            )
        else:
            selected_items = tuple(_selected_items)
            if any(
                item.suggested_provider != "alpha_vantage"
                or item.reconciliation_status not in ("incomplete", "conflict")
                for item in selected_items
            ):
                raise ValueError("El barrido congelado contiene eventos no elegibles.")
            event_keys = [
                (item.instrument_id, item.action_type, item.effective_at)
                for item in selected_items
            ]
            if len(event_keys) != len(set(event_keys)):
                raise ValueError("El barrido congelado contiene eventos duplicados.")
        before_coverage = coverage_service.get_report(as_of=cutoff)
        selected_event_keys: set[EventKey] = {
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
            market_provider=_ExpectedSecondaryProvider(self._history_provider),
            repository=self._repository,
        )

        for index, instrument_id in enumerate(instrument_ids, start=1):
            if _expected_identities is not None:
                current = InstrumentRepository(self._database).get_by_id(instrument_id)
                actual_identity = (
                    tuple(current.get(field) for field in FROZEN_INSTRUMENT_IDENTITY_FIELDS)
                    if current is not None else None
                )
                if actual_identity != _expected_identities.get(instrument_id):
                    failed += 1
                    failures.append({
                        "instrumentId": str(instrument_id), "symbol": "",
                        "error": "frozen_instrument_identity_changed",
                    })
                    self._emit(index, len(instrument_ids), "", "failed_identity", 0)
                    continue
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
            limit=max(1, before_coverage.incomplete_event_count + before_coverage.conflict_event_count + len(selected_items) + 100),
            offset=0,
        )
        after_coverage = coverage_service.get_report(as_of=verification_cutoff)
        remaining_keys = {
            (item.instrument_id, item.action_type, item.effective_at)
            for item in after_worklist.items
            if item.reconciliation_status == "incomplete"
        }
        selected_remaining = len(selected_event_keys & remaining_keys)
        selected_conflicting = sum(
            (item.instrument_id, item.action_type, item.effective_at) in selected_event_keys
            and item.reconciliation_status == "conflict"
            for item in after_worklist.items
        )

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
            selected_events_conflicting=selected_conflicting,
            agreed_before=before_coverage.agreed_event_count,
            agreed_after=after_coverage.agreed_event_count,
            conflicts_before=before_coverage.conflict_event_count,
            conflicts_after=after_coverage.conflict_event_count,
            failures=tuple(failures),
            effective_from_date=effective_from,
            effective_to_date=effective_to,
        )

    def run_sweep(
        self,
        *,
        as_of: datetime,
        limit: int = 10,
        max_batches: int = 20,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Freeze actionable unresolved events before writes shrink the worklist.

        A consistent SQLite backup fixes the selected events and their full
        instrument identities. No live offset pagination occurs after writes.
        """
        cutoff = self._aware_utc(as_of, "as_of")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100.")
        if type(max_batches) is not int or not 1 <= max_batches <= 1000:
            raise ValueError("max_batches debe estar entre 1 y 1000.")
        max_instruments = limit * max_batches
        self._database.initialize()
        with tempfile.TemporaryDirectory(prefix="athena-actions-sweep-") as directory:
            snapshot = Path(directory) / "frozen-actions.db"
            source_path = self._database.database_path.resolve()
            with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(snapshot)) as destination:
                    source.backup(destination)
            with closing(sqlite3.connect(snapshot)) as connection:
                journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
                integrity = connection.execute("PRAGMA quick_check").fetchone()
            if (
                journal_mode is None or journal_mode[0].lower() != "delete"
                or integrity is None or integrity[0] != "ok"
            ):
                raise RuntimeError("La instantánea de corporate actions no es íntegra.")
            with snapshot.open("rb") as stream:
                snapshot_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            frozen_db = ReadOnlySnapshotDatabase(snapshot)
            frozen_worklist = CorporateActionReconciliationWorklistService(frozen_db)
            first = frozen_worklist.get_worklist(as_of=cutoff, limit=500, offset=0)
            unresolved_total = (
                first.total_incomplete_event_count + first.total_conflict_event_count
            )
            selected_by_instrument: dict[int, list[Any]] = {}
            actionable_total = 0
            seen_keys: set[EventKey] = set()
            offset = 0
            while offset < unresolved_total:
                page = first if offset == 0 else frozen_worklist.get_worklist(
                    as_of=cutoff, limit=500, offset=offset,
                )
                if (
                    page.as_of != first.as_of
                    or page.total_incomplete_event_count != first.total_incomplete_event_count
                    or page.total_conflict_event_count != first.total_conflict_event_count
                    or not page.items
                ):
                    raise RuntimeError("La cola congelada cambió durante el barrido.")
                for item in page.items:
                    if item.suggested_provider != "alpha_vantage":
                        continue
                    key = (item.instrument_id, item.action_type, item.effective_at)
                    if key in seen_keys:
                        raise RuntimeError("La cola congelada contiene eventos duplicados.")
                    seen_keys.add(key)
                    actionable_total += 1
                    if (
                        item.instrument_id in selected_by_instrument
                        or len(selected_by_instrument) < max_instruments
                    ):
                        selected_by_instrument.setdefault(item.instrument_id, []).append(item)
                offset += len(page.items)
            frozen_repo = InstrumentRepository(frozen_db)
            expected_identities: dict[int, tuple[Any, ...]] = {}
            for instrument_id in selected_by_instrument:
                instrument = frozen_repo.get_by_id(instrument_id)
                if instrument is None or not bool(instrument.get("is_active")):
                    raise RuntimeError("El instrumento congelado no está activo.")
                expected_identities[instrument_id] = tuple(
                    instrument.get(field) for field in FROZEN_INSTRUMENT_IDENTITY_FIELDS
                )
            with snapshot.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != snapshot_sha:
                    raise RuntimeError("La instantánea cambió durante la selección.")

        instrument_ids = tuple(selected_by_instrument)
        reports: list[VerifiedCorporateActionSecondaryBackfillReport] = []
        for start in range(0, len(instrument_ids), limit):
            batch_ids = instrument_ids[start:start + limit]
            batch_items = tuple(
                item for instrument_id in batch_ids
                for item in selected_by_instrument[instrument_id]
            )
            reports.append(self.run(
                as_of=cutoff, limit=len(batch_ids),
                from_date=from_date, to_date=to_date,
                _selected_items=batch_items,
                _expected_identities={
                    instrument_id: expected_identities[instrument_id]
                    for instrument_id in batch_ids
                },
            ))
        final_cutoff = self._aware_utc(self._clock(), "clock")
        if final_cutoff < cutoff:
            final_cutoff = cutoff
        final = CorporateActionCoverageService(self._database).get_report(as_of=final_cutoff)
        attempted_events = sum(len(items) for items in selected_by_instrument.values())
        failures = sum(report.failed_count for report in reports)
        unattempted_events = actionable_total - attempted_events
        return {
            "status": (
                "completed_with_failures" if failures else
                "bounded_sweep_partial" if unattempted_events else
                "no_actionable_secondary_work" if actionable_total == 0 else
                "bounded_sweep_completed"
            ),
            "asOf": cutoff.isoformat(),
            "verificationAsOf": final_cutoff.isoformat(),
            "frozenSnapshotSha256": snapshot_sha,
            "initialUnresolvedEventCount": unresolved_total,
            "initialActionableSecondaryEventCount": actionable_total,
            "attemptedEventCount": attempted_events,
            "unattemptedActionableEventCount": unattempted_events,
            "attemptedInstrumentCount": len(instrument_ids),
            "failedInstrumentCount": failures,
            "batchCount": len(reports),
            "finalIncompleteEventCount": final.incomplete_event_count,
            "finalConflictEventCount": final.conflict_event_count,
            "completeActionableSelection": unattempted_events == 0,
            "batches": [report.to_api_dict() for report in reports],
            "policy": {
                "sourceSnapshotConsistent": True,
                "frozenInstrumentIdentityCheckedBeforeFetch": True,
                "operationalOriginVerified": False,
                "independentProviderAgreementVerified": False,
                "automaticCanonicalization": False,
                "automaticReadinessPromotion": False,
                "automaticTrading": False,
            },
        }

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
