from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from app.services.alpha_vantage_corporate_action_service import (
    AlphaVantageCorporateActionService,
)
from app.services.verified_corporate_action_secondary_backfill_service import (
    VerifiedCorporateActionSecondaryBackfillService,
)


DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def _progress(event: dict[str, Any]) -> None:
    print(
        "[Corporate actions verified] "
        f"{event['index']}/{event['total']} | "
        f"{event['symbol']} | {event['status']} | "
        f"acciones={event['actions']}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa solo corporate actions PIT que todavía carecen de una segunda "
            "familia configurada, persiste Alpha Vantage y vuelve a medir acuerdo, "
            "conflicto e incompletitud. No canonicaliza conflictos ni promociona readiness."
        )
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--from-date", dest="from_date")
    parser.add_argument("--to-date", dest="to_date")
    parser.add_argument(
        "--as-of",
        dest="as_of",
        help=(
            "Knowledge cutoff ISO con zona horaria. Si se omite usa el instante UTC actual."
        ),
    )
    return parser


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def run(
    *,
    limit: int,
    offset: int,
    from_date: str | None,
    to_date: str | None,
    as_of: datetime,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("--limit debe ser mayor que 0.")
    if limit > MAX_LIMIT:
        raise ValueError(f"--limit no puede superar {MAX_LIMIT} por ejecución.")
    if offset < 0:
        raise ValueError("--offset no puede ser negativo.")

    provider = AlphaVantageCorporateActionService()
    try:
        report = VerifiedCorporateActionSecondaryBackfillService(
            history_provider=provider,
            progress_callback=_progress,
        ).run(
            as_of=as_of,
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
    payload = run(
        limit=args.limit,
        offset=args.offset,
        from_date=args.from_date,
        to_date=args.to_date,
        as_of=_parse_as_of(args.as_of),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
