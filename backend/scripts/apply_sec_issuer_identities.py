from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.sec_issuer_identity_service import SecIssuerIdentityService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Persiste identidades canónicas de emisor para listados estadounidenses "
            "cuando la SEC ofrece una asociación ticker/CIK única. No resuelve ni "
            "modifica todavía el domicilio o la región del emisor."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    return parser


def run(database_path: Path | None = None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    report = SecIssuerIdentityService(database=database).apply()
    return report.to_api_dict()


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run(args.database), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
