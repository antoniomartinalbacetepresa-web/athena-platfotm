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
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)
from app.services.source_aware_universe_import_service import (
    SourceAwareUniverseImportService,
)
from app.services.yahoo_regional_universe_source import (
    YahooRegionalUniverseSource,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Descubre equities por región mediante Yahoo y los importa de "
            "forma acotada en la base local de ATHENA TYCHE."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--regions",
        default=",".join(YahooRegionalUniverseSource.DEFAULT_REGIONS),
        help="Códigos Yahoo separados por comas, por ejemplo de,fr,jp,hk.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Resultados por página (1-250).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Máximo de páginas por región.",
    )
    return parser


def run_import(
    *,
    database_path: Path | None,
    regions: tuple[str, ...],
    page_size: int,
    max_pages: int,
) -> dict[str, object]:
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
    source = YahooRegionalUniverseSource(
        regions=regions,
        page_size=page_size,
        max_pages_per_region=max_pages,
    )

    report = importer.import_source(source)
    quality = (
        PersistedMarketUniverseService(database=database)
        .get_quality_report()
        .to_api_dict()
    )

    return {
        "source": report.source_id,
        "regions": list(regions),
        "pageSize": page_size,
        "maxPagesPerRegion": max_pages,
        "received": report.received,
        "accepted": report.accepted,
        "rejected": report.rejected,
        "inserted": report.inserted,
        "updated": report.updated,
        "unchanged": report.unchanged,
        "deactivated": report.deactivated,
        "reconciliationApplied": report.reconciliation_applied,
        "activeSourceMemberships": memberships.count_active_for_source(
            report.source_id
        ),
        "catalogQuality": quality,
    }


def main() -> int:
    args = build_parser().parse_args()
    regions = tuple(
        part.strip().lower()
        for part in args.regions.split(",")
        if part.strip()
    )
    if not regions:
        raise SystemExit("Debe indicarse al menos una región.")

    result = run_import(
        database_path=args.database,
        regions=regions,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
