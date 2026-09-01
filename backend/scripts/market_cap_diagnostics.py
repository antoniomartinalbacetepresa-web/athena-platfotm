from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.market_cap_coverage_service import MarketCapCoverageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analiza la capitalización persistida de ATHENA TYCHE sin "
            "descargar ni modificar datos."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    return parser


def run_diagnostics(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return (
        MarketCapCoverageService(database=database)
        .get_report()
        .to_api_dict()
    )


def main() -> int:
    args = build_parser().parse_args()
    report = run_diagnostics(args.database)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
