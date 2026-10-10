from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.issuer_region_resolution_service import (
    IssuerRegionResolutionService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resuelve de forma diagnóstica el domicilio regional de emisores "
            "probables que aparecen cotizados en varias regiones."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help=(
            "Máximo de grupos de mayor capitalización a consultar. "
            "Use --all para procesarlos todos."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Procesa todos los grupos con conflicto regional.",
    )
    return parser


def run_diagnostics(
    *,
    database_path: Path | None = None,
    max_groups: int | None = 100,
) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return IssuerRegionResolutionService(database=database).get_report(
        max_groups=max_groups
    ).to_api_dict()


def main() -> int:
    args = build_parser().parse_args()
    if not args.all and args.limit <= 0:
        raise SystemExit("--limit debe ser mayor que 0.")

    max_groups = None if args.all else args.limit
    report = run_diagnostics(
        database_path=args.database,
        max_groups=max_groups,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
