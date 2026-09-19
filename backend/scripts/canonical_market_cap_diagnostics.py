from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.canonical_market_cap_service import CanonicalMarketCapService
from app.services.issuer_identity_coverage_service import IssuerIdentityCoverageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Muestra cobertura de identidad canónica y capitalización deduplicada por "
            "emisor. Es un diagnóstico; no activa todavía pesos regionales."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    return parser


def run(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return {
        "issuerIdentityCoverage": IssuerIdentityCoverageService(
            database=database
        ).get_report().to_api_dict(),
        "canonicalMarketCap": CanonicalMarketCapService(
            database=database
        ).get_report().to_api_dict(),
    }


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run(args.database), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
