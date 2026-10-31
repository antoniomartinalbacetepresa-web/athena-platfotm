from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.verified_market_history_backfill_service import (
    VerifiedMarketHistoryBackfillService,
)


DEFAULT_LIMIT = 25
MAX_LIMIT = 500


def _progress(event: dict[str, Any]) -> None:
    print(
        "[Histórico profundo] "
        f"{event['index']}/{event['total']} | "
        f"{event['symbol']} | {event['status']} | "
        f"observaciones={event['observations']}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta backfill Yahoo solo para instrumentos que bloquean el criterio "
            ">=365 días y vuelve a verificar el criterio sobre datos persistidos."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Bloqueadores a procesar (por defecto {DEFAULT_LIMIT}, máximo {MAX_LIMIT}).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Desplazamiento dentro de la cola actual de bloqueadores históricos.",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        help=(
            "Inicio YYYY-MM-DD. Si se omite, se solicitan automáticamente 400 días "
            "hasta --to-date o hasta la fecha UTC actual."
        ),
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        help="Fecha final inclusiva YYYY-MM-DD.",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Procesa una lista fija y acotada de bloqueos sin saltarlos al cambiar la cola.",
    )
    parser.add_argument(
        "--max-batches", type=int, default=20,
        help="Máximo de lotes en --sweep (1..1000); la cola se pagina sin limitar el universo a 1000.",
    )
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
        raise ValueError(f"--limit no puede superar {MAX_LIMIT} en una ejecución.")
    if offset < 0:
        raise ValueError("--offset no puede ser negativo.")

    report = VerifiedMarketHistoryBackfillService(
        progress_callback=_progress,
    ).run(
        limit=limit,
        offset=offset,
        from_date=from_date,
        to_date=to_date,
    )
    return report.to_api_dict()


def run_sweep(
    *,
    limit: int,
    max_batches: int,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, Any]:
    return VerifiedMarketHistoryBackfillService(
        progress_callback=_progress,
    ).run_sweep(
        limit=limit, max_batches=max_batches,
        from_date=from_date, to_date=to_date,
    )


def main() -> int:
    args = build_parser().parse_args()
    if args.sweep:
        if args.offset:
            raise ValueError("--offset debe ser cero con --sweep.")
        report = run_sweep(
            limit=args.limit, max_batches=args.max_batches,
            from_date=args.from_date, to_date=args.to_date,
        )
    else:
        report = run(
            limit=args.limit, offset=args.offset,
            from_date=args.from_date, to_date=args.to_date,
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exit 0 means the FULL 365-day eligible-universe criterion is satisfied,
    # never merely that a bounded batch finished without an exception.
    if args.sweep:
        ready = report.get("historyReady") is True
    else:
        verification = report.get("verification")
        ready = (
            isinstance(verification, dict)
            and verification.get("deepHistoryCriterionSatisfied") is True
        )
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
