from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.alpha_vantage_corporate_action_service import (
    AlphaVantageCorporateActionService,
)
from app.services.corporate_action_secondary_backfill_service import (
    CorporateActionSecondaryBackfillService,
)


DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def _progress(event: dict[str, Any]) -> None:
    print(
        "[Corporate actions secondary] "
        f"{event['index']}/{event['total']} | "
        f"{event['symbol']} | {event['status']} | "
        f"acciones={event['actions']}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingiere dividendos/splits desde Alpha Vantage como fuente secundaria "
            "PIT. No canonicaliza conflictos ni demuestra independencia productiva."
        )
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--from-date", dest="from_date")
    parser.add_argument("--to-date", dest="to_date")
    return parser


def run(
    *,
    limit: int,
    offset: int,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("--limit debe ser mayor que 0.")
    if limit > MAX_LIMIT:
        raise ValueError(f"--limit no puede superar {MAX_LIMIT} por ejecución.")
    if offset < 0:
        raise ValueError("--offset no puede ser negativo.")

    provider = AlphaVantageCorporateActionService()
    try:
        report = CorporateActionSecondaryBackfillService(
            history_provider=provider,
            progress_callback=_progress,
        ).run(
            limit=limit,
            offset=offset,
            from_date=from_date,
            to_date=to_date,
        )
        return report.to_api_dict()
    finally:
        provider.close()


def main() -> None:
    args = build_parser().parse_args()
    report = run(
        limit=args.limit,
        offset=args.offset,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
