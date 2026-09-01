from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.sec_issuer_resolution_preview_service import (
    SecIssuerResolutionPreviewService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara los listados estadounidenses persistidos de ATHENA TYCHE "
            "con las asociaciones oficiales SEC CIK/ticker/exchange. No modifica datos."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    return parser


def run_preview(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return (
        SecIssuerResolutionPreviewService(database=database)
        .get_report()
        .to_api_dict()
    )


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run_preview(args.database), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
