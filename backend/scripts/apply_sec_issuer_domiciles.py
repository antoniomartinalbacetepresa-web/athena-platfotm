from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.sec_issuer_domicile_service import SecIssuerDomicileService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enriquece por lotes el domicilio de emisores canónicos ya identificados "
            "por SEC CIK. Sólo persiste países/regiones inequívocos y soportados."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=100)
    return parser


def run(
    database_path: Path | None = None,
    *,
    limit: int = 100,
) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    report = SecIssuerDomicileService(database=database).apply(limit=limit)
    return report.to_api_dict()


def main() -> int:
    args = build_parser().parse_args()
    print(
        json.dumps(
            run(args.database, limit=args.limit),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
