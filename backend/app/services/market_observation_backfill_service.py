from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any, Callable, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService
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
TodayProvider = Callable[[], date]


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
    selection_mode: str = "active_universe"
    effective_from_date: str | None = None
    effective_to_date: str | None = None
    history_window_auto_expanded: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "completed_with_failures" if self.failed_count else "completed",
            "selectionMode": self.selection_mode,
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
            "historyWindow": {
                "fromDate": self.effective_from_date,
                "toDate": self.effective_to_date,
                "autoExpandedForBlockers": self.history_window_auto_expanded,
            },
            "failures": [dict(item) for item in self.failures],
            "pointInTimeOverwritePolicy": "preserve_first_observation_per_source",
        }


class MarketObservationBackfillService:
    _EXCLUDED_TYPES = frozenset({"etf", "fund"})
    _DEEP_HISTORY_DAYS = 365
    _BLOCKER_LOOKBACK_MARGIN_DAYS = 35
    BLOCKER_LOOKBACK_DAYS = _DEEP_HISTORY_DAYS + _BLOCKER_LOOKBACK_MARGIN_DAYS

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        history_provider: MarketHistoryProvider | None = None,
        progress_callback: ProgressCallback | None = None,
        today_provider: TodayProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._instruments = InstrumentRepository(database=self._database)
        self._observations = MarketObservationRepository(database=self._database)
        self._history_provider = (
            history_provider if history_provider is not None else YahooMarketService()
        )
        self._progress_callback = progress_callback
        self._today_provider = (
            today_provider
            if today_provider is not None
            else lambda: datetime.now(timezone.utc).date()
        )

    def run(
        self,
        *,
        limit: int,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
        source_provider: str = YahooMarketService.PROVIDER_ID,
        blocking_only: bool = False,
        _instrument_ids: tuple[int, ...] | None = None,
    ) -> MarketObservationBackfillReport:
        if _instrument_ids is not None:
            if not blocking_only or offset != 0:
                raise ValueError("La selección fija requiere blocking_only y offset cero.")
            if (
                not isinstance(_instrument_ids, tuple)
                or not _instrument_ids
                or len(_instrument_ids) > limit
                or any(type(value) is not int or value <= 0 for value in _instrument_ids)
                or len(set(_instrument_ids)) != len(_instrument_ids)
            ):
                raise ValueError("La selección fija debe contener IDs únicos, positivos y acotados.")
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")
        provider = str(source_provider or "").strip()
        if not provider:
            raise ValueError("source_provider es obligatorio.")
        # A configured adapter must not be relabelled as another source,
        # even if its observations omit sourceProvider metadata.
        adapter_provider = getattr(self._history_provider, "PROVIDER_ID", None)
        if adapter_provider is not None and str(adapter_provider).strip() != provider:
            raise ValueError(
                "La identidad del proveedor histórico no coincide con source_provider."
            )

        effective_from_date, effective_to_date, auto_expanded = self._resolve_history_window(
            from_date=from_date,
            to_date=to_date,
            blocking_only=blocking_only,
        )

        self._database.initialize()
        rows = self._select_rows(
            limit=limit,
            offset=offset,
            blocking_only=blocking_only,
            instrument_ids=_instrument_ids,
            as_of_date=(
                self._parse_iso_date(effective_to_date, field="to_date")
                if effective_to_date is not None
                else self._today_provider()
            ),
        )
        # PIT knowledge time must not precede the network response.
        # A batch can take minutes; capture this independently for each symbol.

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
                    from_date=effective_from_date,
                    to_date=effective_to_date,
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

                self._validate_source_provenance(
                    observations=history,
                    expected_provider=provider,
                    expected_symbol=symbol,
                )
                # The observation was not available when the batch began.
                # Recording that earlier time would create false PIT knowledge.
                retrieved_at = datetime.now(timezone.utc)
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
            selection_mode=("history_blockers" if blocking_only else "active_universe"),
            effective_from_date=effective_from_date,
            effective_to_date=effective_to_date,
            history_window_auto_expanded=auto_expanded,
        )

    def _validate_source_provenance(
        self,
        *,
        observations: list[dict[str, Any]],
        expected_provider: str,
        expected_symbol: str,
    ) -> None:
        for observation in observations:
            if not isinstance(observation, dict):
                raise ValueError("El histórico contiene una observación no estructurada.")
            # Older historical adapters may omit symbol, but an explicitly
            # declared symbol must never contradict the selected instrument.
            declared_symbol_raw = observation.get("symbol")
            if declared_symbol_raw is not None:
                declared_symbol = str(declared_symbol_raw).strip().upper()
                if not declared_symbol or declared_symbol != expected_symbol:
                    raise ValueError(
                        "El símbolo declarado del histórico no coincide con el instrumento."
                    )
            # Both aliases are untrusted input: validating only the first
            # allows a conflicting second declaration to be silently ignored.
            declared_values = [
                observation[key]
                for key in ("sourceProvider", "source_provider")
                if key in observation
            ]
            if not declared_values:
                # Legacy Yahoo adapters may omit the field; an independent
                # secondary source must provide explicit provenance.
                if expected_provider != YahooMarketService.PROVIDER_ID:
                    raise ValueError(
                        "La procedencia del histórico secundario debe declararse."
                    )
                continue
            for declared_raw in declared_values:
                declared = str(declared_raw or "").strip()
                if not declared:
                    raise ValueError(
                        "sourceProvider no puede estar vacío cuando está presente."
                    )
                if declared != expected_provider:
                    raise ValueError(
                        "La procedencia del histórico no coincide con source_provider; "
                        "se rechaza la persistencia para evitar provenance incorrecto."
                    )

    def _resolve_history_window(
        self,
        *,
        from_date: str | None,
        to_date: str | None,
        blocking_only: bool,
    ) -> tuple[str | None, str | None, bool]:
        # Reject impossible or future windows before database selection or network I/O.
        start = self._parse_iso_date(from_date, field="from_date") if from_date is not None else None
        end = self._parse_iso_date(to_date, field="to_date") if to_date is not None else None
        today = self._today_provider()
        if start is not None and start > today:
            raise ValueError("from_date no puede ser una fecha futura.")
        if end is not None and end > today:
            raise ValueError("to_date no puede ser una fecha futura.")
        if start is not None and end is not None and start > end:
            raise ValueError("from_date no puede ser posterior a to_date.")

        if not blocking_only or start is not None:
            return (
                start.isoformat() if start is not None else None,
                end.isoformat() if end is not None else None,
                False,
            )

        end_date = end if end is not None else today
        start_date = end_date - timedelta(days=self.BLOCKER_LOOKBACK_DAYS)
        return start_date.isoformat(), end_date.isoformat(), True

    def _parse_iso_date(self, value: str, *, field: str) -> date:
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError(f"{field} debe tener formato YYYY-MM-DD y ser una fecha válida.")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} debe tener formato YYYY-MM-DD y ser una fecha válida.") from exc

    def _select_rows(
        self,
        *,
        limit: int,
        offset: int,
        blocking_only: bool,
        instrument_ids: tuple[int, ...] | None,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        if instrument_ids is not None:
            rows: list[dict[str, Any]] = []
            for instrument_id in instrument_ids:
                row = self._instruments.get_by_id(instrument_id)
                if row is None or not bool(row.get("is_active")):
                    raise RuntimeError("Un instrumento del lote fijo ya no está activo.")
                rows.append(row)
            return rows
        if not blocking_only:
            return self._instruments.list_active(limit=limit, offset=offset)

        report = MarketHistoryGapService(database=self._database).get_report(
            limit=limit,
            offset=offset,
            as_of=datetime.combine(as_of_date, time.max, tzinfo=timezone.utc),
        )
        rows: list[dict[str, Any]] = []
        for blocker in report.items:
            row = self._instruments.get_by_id(blocker.instrument_id)
            if row is None or not bool(row.get("is_active")):
                raise RuntimeError(
                    "El diagnóstico histórico cambió durante la selección del backfill."
                )
            rows.append(row)
        return rows

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