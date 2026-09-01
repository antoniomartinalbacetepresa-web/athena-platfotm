from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.yahoo_market_service import YahooMarketService


class MarketHistoryProvider(Protocol):
    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class MarketObservationBackfillReport:
    selected_count: int
    processed_count: int
    persisted_instrument_count: int
    skipped_non_equity_count: int
    no_history_count: int
    failed_count: int
    observations_received: int
    observations_inserted: int
    observations_unchanged: int
    failures: tuple[dict[str, str], ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "completed_with_failures" if self.failed_count else "completed",
            "selectedCount": self.selected_count,
            "processedCount": self.processed_count,
            "persistedInstrumentCount": self.persisted_instrument_count,
            "skippedNonEquityCount": self.skipped_non_equity_count,
            "noHistoryCount": self.no_history_count,
            "failedCount": self.failed_count,
            "observations": {
                "received": self.observations_received,
                "inserted": self.observations_inserted,
                "unchanged": self.observations_unchanged,
            },
            "failures": [dict(item) for item in self.failures],
            "pointInTimeOverwritePolicy": "preserve_first_observation_per_source",
        }


class MarketObservationBackfillService:
    _EXCLUDED_TYPES = frozenset({"etf", "fund"})

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: MarketHistoryProvider | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._instruments = InstrumentRepository(database=self._database)
        self._observations = MarketObservationRepository(database=self._database)
        self._history_provider = (
            history_provider if history_provider is not None else YahooMarketService()
        )
        self._progress_callback = progress_callback

    def run(
        self,
        *,
        limit: int,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
        source_provider: str = "yahoo_finance",
    ) -> MarketObservationBackfillReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")
        provider = str(source_provider or "").strip()
        if not provider:
            raise ValueError("source_provider es obligatorio.")

        self._database.initialize()
        rows = self._instruments.list_active(limit=limit, offset=offset)
        retrieved_at = datetime.now(timezone.utc)

        persisted_instruments = 0
        skipped_non_equity = 0
        no_history = 0
        failed = 0
        received = 0
        inserted = 0
        unchanged = 0
        failures: list[dict[str, str]] = []

        for index, row in enumerate(rows, start=1):
            instrument_id = int(row["id"])
            symbol = str(row.get("symbol") or "").strip().upper()
            instrument_type = str(row.get("instrument_type") or "unknown").strip().lower()

            if instrument_type in self._EXCLUDED_TYPES:
                skipped_non_equity += 1
                self._emit(
                    symbol=symbol,
                    index=index,
                    total=len(rows),
                    status="skipped_non_equity",
                    observations=0,
                )
                continue

            try:
                history = self._history_provider.get_history(
                    symbol=symbol,
                    from_date=from_date,
                    to_date=to_date,
                )
                if not history:
                    no_history += 1
                    self._emit(
                        symbol=symbol,
                        index=index,
                        total=len(rows),
                        status="no_history",
                        observations=0,
                    )
                    continue

                stats = self._observations.save_many(
                    instrument_id=instrument_id,
                    observations=history,
                    source_provider=provider,
                    retrieved_at=retrieved_at,
                )
                persisted_instruments += 1
                received += stats.received
                inserted += stats.inserted
                unchanged += stats.unchanged
                self._emit(
                    symbol=symbol,
                    index=index,
                    total=len(rows),
                    status="persisted",
                    observations=stats.received,
                )
            except Exception as exc:
                failed += 1
                failures.append(
                    {
                        "symbol": symbol,
                        "error": str(exc),
                    }
                )
                self._emit(
                    symbol=symbol,
                    index=index,
                    total=len(rows),
                    status="failed",
                    observations=0,
                )

        return MarketObservationBackfillReport(
            selected_count=len(rows),
            processed_count=len(rows),
            persisted_instrument_count=persisted_instruments,
            skipped_non_equity_count=skipped_non_equity,
            no_history_count=no_history,
            failed_count=failed,
            observations_received=received,
            observations_inserted=inserted,
            observations_unchanged=unchanged,
            failures=tuple(failures),
        )

    def _emit(
        self,
        *,
        symbol: str,
        index: int,
        total: int,
        status: str,
        observations: int,
    ) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(
            {
                "symbol": symbol,
                "index": index,
                "total": total,
                "status": status,
                "observations": observations,
            }
        )
