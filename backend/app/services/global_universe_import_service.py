from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.universe_import_run_repository import (
    UniverseImportRunRepository,
)


class InstrumentUniverseSource(Protocol):
    @property
    def source_id(self) -> str:
        ...

    def get_instruments(
        self,
    ) -> Iterable[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class UniverseImportReport:
    source_id: str

    received: int
    accepted: int
    rejected: int

    inserted: int
    updated: int
    unchanged: int

    deactivated: int
    reconciliation_applied: bool

    started_at: str
    completed_at: str

    rejected_records: tuple[
        dict[str, Any],
        ...
    ]

    @property
    def created_or_updated(self) -> int:
        return self.inserted + self.updated


class GlobalUniverseImportService:
    DEFAULT_MINIMUM_RECONCILIATION_COVERAGE = 0.95

    def __init__(
        self,
        repository: InstrumentRepository | None = None,
        run_repository: UniverseImportRunRepository | None = None,
        minimum_reconciliation_coverage: float = (
            DEFAULT_MINIMUM_RECONCILIATION_COVERAGE
        ),
    ) -> None:
        self._repository = (
            repository
            if repository is not None
            else InstrumentRepository()
        )

        self._run_repository = (
            run_repository
            if run_repository is not None
            else UniverseImportRunRepository()
        )

        if not (
            0.0
            < minimum_reconciliation_coverage
            <= 1.0
        ):
            raise ValueError(
                "minimum_reconciliation_coverage "
                "debe ser mayor que 0 y menor "
                "o igual que 1."
            )

        self._minimum_reconciliation_coverage = (
            float(
                minimum_reconciliation_coverage
            )
        )

    def import_source(
        self,
        source: InstrumentUniverseSource,
    ) -> UniverseImportReport:
        started_at = self._now()

        source_id = self._normalize_source_id(
            source.source_id
        )

        run_id = self._run_repository.start_run(
            source_id=source_id,
            started_at=started_at,
        )

        received = 0

        accepted_records: list[
            dict[str, Any]
        ] = []

        rejected_records: list[
            dict[str, Any]
        ] = []

        seen_listing_keys: set[str] = set()

        inserted = 0
        updated = 0
        unchanged = 0

        deactivated = 0
        reconciliation_applied = False

        previous_active_count = 0

        try:
            previous_active_count = (
                self._repository.count_active_for_source(
                    source_id
                )
            )

            for raw_instrument in source.get_instruments():
                received += 1

                try:
                    instrument = self._prepare_instrument(
                        raw_instrument=raw_instrument,
                        source_id=source_id,
                    )

                    listing_key = self._listing_key(
                        instrument
                    )

                    if listing_key in seen_listing_keys:
                        rejected_records.append(
                            {
                                "record": raw_instrument,
                                "reason": (
                                    "Cotización duplicada "
                                    "dentro de la misma importación."
                                ),
                            }
                        )

                        continue

                    seen_listing_keys.add(
                        listing_key
                    )

                    accepted_records.append(
                        instrument
                    )
                except ValueError as exc:
                    rejected_records.append(
                        {
                            "record": raw_instrument,
                            "reason": str(exc),
                        }
                    )

            source_owned_records = [
                instrument
                for instrument in accepted_records
                if self._instrument_belongs_to_source(
                    instrument=instrument,
                    source_id=source_id,
                )
            ]

            source_owned_active_listings = {
                self._listing_identity(
                    instrument
                )
                for instrument
                in source_owned_records
            }

            if accepted_records:
                stats = self._repository.upsert_many_with_stats(
                    accepted_records
                )

                inserted = stats.inserted
                updated = stats.updated
                unchanged = stats.unchanged

                if stats.processed != len(
                    accepted_records
                ):
                    raise RuntimeError(
                        "Las estadísticas de persistencia "
                        "no coinciden con los registros aceptados."
                    )

                if (
                    inserted
                    + updated
                    + unchanged
                    != len(accepted_records)
                ):
                    raise RuntimeError(
                        "Las estadísticas de cambios "
                        "no son consistentes."
                    )

            if (
                not rejected_records
                and self._should_reconcile(
                    previous_active_count=previous_active_count,
                    current_source_owned_count=len(
                        source_owned_active_listings
                    ),
                )
            ):
                deactivated = (
                    self._repository.deactivate_missing_for_source(
                        source_provider=source_id,
                        active_listings=(
                            source_owned_active_listings
                        ),
                    )
                )

                reconciliation_applied = True

            completed_at = self._now()

            self._run_repository.mark_succeeded(
                run_id,
                received=received,
                accepted=len(
                    accepted_records
                ),
                rejected=len(
                    rejected_records
                ),
                inserted=inserted,
                updated=updated,
                unchanged=unchanged,
                deactivated=deactivated,
                reconciliation_applied=reconciliation_applied,
                completed_at=completed_at,
            )

            return UniverseImportReport(
                source_id=source_id,
                received=received,
                accepted=len(
                    accepted_records
                ),
                rejected=len(
                    rejected_records
                ),
                inserted=inserted,
                updated=updated,
                unchanged=unchanged,
                deactivated=deactivated,
                reconciliation_applied=(
                    reconciliation_applied
                ),
                started_at=started_at,
                completed_at=completed_at,
                rejected_records=tuple(
                    rejected_records
                ),
            )
        except Exception as exc:
            completed_at = self._now()

            try:
                self._run_repository.mark_failed(
                    run_id,
                    error_message=str(
                        exc
                    ) or exc.__class__.__name__,
                    received=received,
                    accepted=len(
                        accepted_records
                    ),
                    rejected=len(
                        rejected_records
                    ),
                    created_or_updated=0,
                    completed_at=completed_at,
                )
            except Exception:
                pass

            raise

    def import_sources(
        self,
        sources: Iterable[
            InstrumentUniverseSource
        ],
    ) -> list[UniverseImportReport]:
        reports: list[
            UniverseImportReport
        ] = []

        for source in sources:
            report = self.import_source(
                source
            )

            reports.append(
                report
            )

        return reports

    def _should_reconcile(
        self,
        previous_active_count: int,
        current_source_owned_count: int,
    ) -> bool:
        if previous_active_count <= 0:
            return False

        if current_source_owned_count <= 0:
            return False

        coverage = (
            current_source_owned_count
            / previous_active_count
        )

        return (
            coverage
            >= self._minimum_reconciliation_coverage
        )

    def _instrument_belongs_to_source(
        self,
        instrument: dict[str, Any],
        source_id: str,
    ) -> bool:
        source_provider = self._optional_text(
            instrument.get(
                "sourceProvider"
            )
        )

        if source_provider is None:
            return False

        return (
            source_provider.strip().lower()
            == source_id
        )

    def _listing_identity(
        self,
        instrument: dict[str, Any],
    ) -> tuple[str, str | None]:
        symbol = self._required_text(
            instrument.get(
                "symbol"
            ),
            "symbol",
        ).upper()

        exchange_short_name = (
            self._optional_text(
                instrument.get(
                    "exchangeShortName"
                )
            )
        )

        if exchange_short_name is not None:
            exchange_short_name = (
                exchange_short_name.upper()
            )

        return (
            symbol,
            exchange_short_name,
        )

    def _prepare_instrument(
        self,
        raw_instrument: dict[str, Any],
        source_id: str,
    ) -> dict[str, Any]:
        if not isinstance(
            raw_instrument,
            dict,
        ):
            raise ValueError(
                "El instrumento debe ser un objeto."
            )

        symbol = self._required_text(
            raw_instrument.get(
                "symbol"
            ),
            "symbol",
        ).upper()

        company_name = self._required_text(
            raw_instrument.get(
                "companyName"
            ),
            "companyName",
        )

        exchange_short_name = (
            self._optional_text(
                raw_instrument.get(
                    "exchangeShortName"
                )
            )
        )

        if exchange_short_name is not None:
            exchange_short_name = (
                exchange_short_name.upper()
            )

        retrieved_at = (
            self._optional_text(
                raw_instrument.get(
                    "retrievedAt"
                )
            )
            or self._now()
        )

        result = dict(
            raw_instrument
        )

        result["symbol"] = symbol
        result["companyName"] = company_name

        result[
            "exchangeShortName"
        ] = exchange_short_name

        result["sourceProvider"] = (
            self._optional_text(
                raw_instrument.get(
                    "sourceProvider"
                )
            )
            or source_id
        )

        result["retrievedAt"] = (
            retrieved_at
        )

        if "isActive" not in result:
            result["isActive"] = True

        return result

    def _listing_key(
        self,
        instrument: dict[str, Any],
    ) -> str:
        symbol = self._required_text(
            instrument.get(
                "symbol"
            ),
            "symbol",
        ).upper()

        exchange_short_name = (
            self._optional_text(
                instrument.get(
                    "exchangeShortName"
                )
            )
        )

        if exchange_short_name is None:
            return f"{symbol}@"

        return (
            f"{symbol}@"
            f"{exchange_short_name.upper()}"
        )

    def _normalize_source_id(
        self,
        source_id: str,
    ) -> str:
        normalized = str(
            source_id
        ).strip().lower()

        if not normalized:
            raise ValueError(
                "source_id es obligatorio."
            )

        return normalized

    def _required_text(
        self,
        value: Any,
        field_name: str,
    ) -> str:
        if value is None:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        return normalized

    def _optional_text(
        self,
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized

    def _now(self) -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()



