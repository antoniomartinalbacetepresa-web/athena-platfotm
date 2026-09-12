from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.alpha_vantage_corporate_action_service import (
    AlphaVantageCorporateActionService,
)
from app.services.corporate_action_ingestion_service import CorporateActionIngestionService


class CorporateActionHistoryProvider(Protocol):
    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]: ...


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class CorporateActionSecondaryBackfillReport:
    selected_count: int
    processed_count: int
    persisted_instrument_count: int
    skipped_non_equity_count: int
    no_action_count: int
    failed_count: int
    actions_received: int
    actions_inserted: int
    actions_unchanged: int
    failures: tuple[dict[str, str], ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "completed_with_failures" if self.failed_count else "completed",
            "provider": "alpha_vantage",
            "selectedCount": self.selected_count,
            "processedCount": self.processed_count,
            "persistedInstrumentCount": self.persisted_instrument_count,
            "skippedNonEquityCount": self.skipped_non_equity_count,
            "noActionCount": self.no_action_count,
            "failedCount": self.failed_count,
            "actions": {
                "received": self.actions_received,
                "inserted": self.actions_inserted,
                "unchanged": self.actions_unchanged,
            },
            "failures": [dict(item) for item in self.failures],
            "canonicalization": "forbidden",
            "productionIndependenceClaimed": False,
        }


class CorporateActionSecondaryBackfillService:
    """Persist secondary-source observations without canonicalizing conflicts."""

    _EXCLUDED_TYPES = frozenset({"etf", "fund"})

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: CorporateActionHistoryProvider | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._instruments = InstrumentRepository(database=self._database)
        self._repository = CorporateActionRepository(database=self._database)
        self._history_provider = (
            history_provider
            if history_provider is not None
            else AlphaVantageCorporateActionService()
        )
        self._progress_callback = progress_callback

    def run(
        self,
        *,
        limit: int,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> CorporateActionSecondaryBackfillReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        rows = self._instruments.list_active(limit=limit, offset=offset)
        ingestion = CorporateActionIngestionService(
            market_provider=self._history_provider,
            repository=self._repository,
        )

        persisted = 0
        skipped = 0
        no_action = 0
        failed = 0
        received = 0
        inserted = 0
        unchanged = 0
        failures: list[dict[str, str]] = []

        for index, row in enumerate(rows, start=1):
            instrument_id = int(row["id"])
            symbol = str(row.get("symbol") or "").strip().upper()
            instrument_type = str(row.get("instrument_type") or "unknown").strip().lower()
            currency_raw = row.get("currency")
            currency = str(currency_raw).strip().upper() if currency_raw is not None else None

            if instrument_type in self._EXCLUDED_TYPES:
                skipped += 1
                self._emit(symbol, index, len(rows), "skipped_non_equity", 0)
                continue

            try:
                stats = ingestion.ingest_history(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    from_date=from_date,
                    to_date=to_date,
                    dividend_currency=currency,
                )
                received += stats.actions_received
                inserted += stats.inserted
                unchanged += stats.unchanged
                if stats.actions_received == 0:
                    no_action += 1
                    status = "no_actions"
                else:
                    persisted += 1
                    status = "persisted"
                self._emit(symbol, index, len(rows), status, stats.actions_received)
            except Exception as exc:
                failed += 1
                failures.append({"symbol": symbol, "error": str(exc)})
                self._emit(symbol, index, len(rows), "failed", 0)

        return CorporateActionSecondaryBackfillReport(
            selected_count=len(rows),
            processed_count=len(rows),
            persisted_instrument_count=persisted,
            skipped_non_equity_count=skipped,
            no_action_count=no_action,
            failed_count=failed,
            actions_received=received,
            actions_inserted=inserted,
            actions_unchanged=unchanged,
            failures=tuple(failures),
        )

    def _emit(
        self,
        symbol: str,
        index: int,
        total: int,
        status: str,
        actions: int,
    ) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(
            {
                "symbol": symbol,
                "index": index,
                "total": total,
                "status": status,
                "actions": actions,
            }
        )
