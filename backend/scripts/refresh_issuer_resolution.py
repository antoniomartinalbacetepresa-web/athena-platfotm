from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.issuer_resolution_pipeline_service import (
    IssuerResolutionPipelineService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta en una sola orden la resolución canónica de emisores SEC, el "
            "enriquecimiento limitado de domicilio y los diagnósticos de cobertura, "
            "capitalización y listado canónico. No activa pesos regionales."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--domicile-limit", type=int, default=100)
    return parser


def run(
    database_path: Path | None = None,
    *,
    domicile_limit: int = 100,
) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return IssuerResolutionPipelineService(database=database).run(
        domicile_limit=domicile_limit
    ).to_api_dict()


def main() -> int:
    args = build_parser().parse_args()
    print(
        json.dumps(
            run(args.database, domicile_limit=args.domicile_limit),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
