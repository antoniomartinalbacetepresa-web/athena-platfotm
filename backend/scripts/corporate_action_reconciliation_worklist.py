from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app.services.corporate_action_reconciliation_worklist_service import (
    CorporateActionReconciliationWorklistService,
)


DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _aware_iso(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lista corporate actions visibles PIT que todavía carecen de dos familias "
            "de proveedor técnicamente independientes."
        )
    )
    parser.add_argument("--as-of", dest="as_of", help="Corte ISO-8601 con zona horaria.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    return parser


def run(*, as_of: str | None, limit: int, offset: int) -> dict[str, object]:
    if limit <= 0 or limit > MAX_LIMIT:
        raise ValueError(f"--limit debe estar entre 1 y {MAX_LIMIT}.")
    if offset < 0:
        raise ValueError("--offset no puede ser negativo.")
    return CorporateActionReconciliationWorklistService().get_worklist(
        as_of=_aware_iso(as_of),
        limit=limit,
        offset=offset,
    ).to_api_dict()


def main() -> None:
    args = build_parser().parse_args()
    print(
        json.dumps(
            run(as_of=args.as_of, limit=args.limit, offset=args.offset),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
