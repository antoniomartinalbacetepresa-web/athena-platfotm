from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.instrument_source_membership_repository import (
    InstrumentSourceMembershipRepository,
)
from app.repositories.universe_import_run_repository import (
    UniverseImportRunRepository,
)
from app.services.global_universe_import_service import GlobalUniverseImportService
from app.services.nasdaq_trader_universe_source import NasdaqTraderUniverseSource
from app.services.source_aware_universe_import_service import (
    SourceAwareUniverseImportService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Importa el catálogo oficial de Nasdaq Trader en la base local "
            "de ATHENA TYCHE y registra su procedencia."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "Ruta opcional de la base SQLite. Si se omite, se usa "
            "ATHENA_DATABASE_PATH o database/athena_tyche.db."
        ),
    )
    return parser


def run_import(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    database.initialize()

    instruments = InstrumentRepository(database=database)
    memberships = InstrumentSourceMembershipRepository(database=database)
    runs = UniverseImportRunRepository(database=database)

    base_import = GlobalUniverseImportService(
        repository=instruments,
        run_repository=runs,
    )
    importer = SourceAwareUniverseImportService(
        import_service=base_import,
        instrument_repository=instruments,
        membership_repository=memberships,
    )

    source = NasdaqTraderUniverseSource()
    try:
        report = importer.import_source(source)
    finally:
        source.dispose()

    return {
        "source": report.source_id,
        "received": report.received,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "inserted": report.inserted,
        "updated": report.updated,
        "unchanged": report.unchanged,
        "deactivated": report.deactivated,
        "reconciliationApplied": report.reconciliation_applied,
        "startedAt": report.started_at,
        "completedAt": report.completed_at,
        "activeSourceMemberships": memberships.count_active_for_source(
            report.source_id
        ),
    }


def main() -> int:
    args = build_parser().parse_args()
    result = run_import(args.database)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
