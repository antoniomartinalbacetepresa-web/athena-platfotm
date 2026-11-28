from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Muestra la calidad del catálogo de mercado local de ATHENA TYCHE."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Ruta opcional de la base SQLite a inspeccionar.",
    )
    return parser


def get_status(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    database.initialize()
    service = PersistedMarketUniverseService(database=database)
    return service.get_quality_report().to_api_dict()


def main() -> int:
    args = build_parser().parse_args()
    print(
        json.dumps(
            get_status(args.database),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
