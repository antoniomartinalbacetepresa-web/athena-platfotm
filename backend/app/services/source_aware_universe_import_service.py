from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.instrument_source_membership_repository import (
    InstrumentSourceMembershipRepository,
)
from app.services.global_universe_import_service import (
    GlobalUniverseImportService,
    InstrumentUniverseSource,
    UniverseImportReport,
)


@dataclass(frozen=True)
class _BufferedUniverseSource:
    source_id: str
    instruments: tuple[dict[str, Any], ...]

    def get_instruments(self) -> Iterable[dict[str, Any]]:
        return iter(self.instruments)


class SourceAwareUniverseImportService:
    """Imports a catalog and tracks source membership independently."""

    DEFAULT_MINIMUM_RECONCILIATION_COVERAGE = 0.95

    def __init__(
        self,
        *,
        import_service: GlobalUniverseImportService,
        instrument_repository: InstrumentRepository,
        membership_repository: InstrumentSourceMembershipRepository,
        minimum_reconciliation_coverage: float = (
            DEFAULT_MINIMUM_RECONCILIATION_COVERAGE
        ),
    ) -> None:
        if not 0 < minimum_reconciliation_coverage <= 1:
            raise ValueError(
                "minimum_reconciliation_coverage debe estar entre 0 y 1."
            )

        self._import_service = import_service
        self._instrument_repository = instrument_repository
        self._membership_repository = membership_repository
        self._minimum_reconciliation_coverage = float(
            minimum_reconciliation_coverage
        )

    def import_source(
        self,
        source: InstrumentUniverseSource,
    ) -> UniverseImportReport:
        source_id = str(source.source_id).strip().lower()
        if not source_id:
            raise ValueError("source_id es obligatorio.")

        previous_active_count = (
            self._membership_repository.count_active_for_source(source_id)
        )

        buffered = tuple(
            dict(item)
            for item in source.get_instruments()
            if isinstance(item, dict)
        )

        report = self._import_service.import_source(
            _BufferedUniverseSource(
                source_id=source_id,
                instruments=buffered,
            )
        )

        instrument_ids = self._resolve_instrument_ids(buffered)

        self._membership_repository.mark_seen_many(
            source_id=source_id,
            instrument_ids=instrument_ids,
            seen_at=report.completed_at,
        )

        if self._should_reconcile_memberships(
            previous_active_count=previous_active_count,
            current_active_count=len(instrument_ids),
            rejected=report.rejected,
        ):
            self._membership_repository.deactivate_missing_for_source(
                source_id=source_id,
                active_instrument_ids=instrument_ids,
            )

        return report

    def _should_reconcile_memberships(
        self,
        *,
        previous_active_count: int,
        current_active_count: int,
        rejected: int,
    ) -> bool:
        if rejected > 0:
            return False
        if previous_active_count <= 0 or current_active_count <= 0:
            return False

        coverage = current_active_count / previous_active_count
        return coverage >= self._minimum_reconciliation_coverage

    def _resolve_instrument_ids(
        self,
        instruments: Iterable[dict[str, Any]],
    ) -> list[int]:
        result: list[int] = []
        seen_ids: set[int] = set()

        for instrument in instruments:
            symbol = str(instrument.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            exchange_value = instrument.get("exchangeShortName")
            exchange = (
                str(exchange_value).strip().upper()
                if exchange_value is not None and str(exchange_value).strip()
                else None
            )

            stored = self._instrument_repository.get_by_listing(
                symbol,
                exchange,
            )

            if stored is None:
                continue

            instrument_id = int(stored["id"])
            if instrument_id in seen_ids:
                continue

            seen_ids.add(instrument_id)
            result.append(instrument_id)

        return result
