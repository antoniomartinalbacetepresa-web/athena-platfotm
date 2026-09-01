from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.issuer_resolution_diagnostics_service import (
    IssuerResolutionDiagnosticsService,
)
from app.services.market_cap_coverage_service import MarketCapCoverageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analiza la capitalización e identidad de emisores persistidas de "
            "ATHENA TYCHE sin descargar ni modificar datos."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    return parser


def run_diagnostics(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    market_cap_report = (
        MarketCapCoverageService(database=database)
        .get_report()
        .to_api_dict()
    )
    issuer_resolution_report = (
        IssuerResolutionDiagnosticsService(database=database)
        .get_report()
        .to_api_dict()
    )

    return {
        **market_cap_report,
        "issuerResolution": issuer_resolution_report,
    }


def main() -> int:
    args = build_parser().parse_args()
    report = run_diagnostics(args.database)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
