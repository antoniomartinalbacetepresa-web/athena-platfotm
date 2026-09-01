from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.market_observation_backfill_service import (
    MarketObservationBackfillService,
)


DEFAULT_LIMIT = 25
MAX_LIMIT = 500


def _progress(event: dict[str, Any]) -> None:
    print(
        "[Mercado] "
        f"{event['index']}/{event['total']} | "
        f"{event['symbol']} | "
        f"{event['status']} | "
        f"observaciones={event['observations']}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guarda histórico diario de mercado en market_observations sin "
            "sobrescribir observaciones point-in-time ya persistidas."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Instrumentos a procesar (por defecto {DEFAULT_LIMIT}, máximo {MAX_LIMIT}).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Desplazamiento dentro de instrumentos activos ordenados por símbolo.",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        help="Fecha inicial YYYY-MM-DD. Si se omite Yahoo usa su ventana predeterminada.",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        help="Fecha final inclusiva YYYY-MM-DD.",
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
        raise ValueError(
            f"--limit no puede superar {MAX_LIMIT} en una sola ejecución."
        )
    if offset < 0:
        raise ValueError("--offset no puede ser negativo.")

    report = MarketObservationBackfillService(
        progress_callback=_progress,
    ).run(
        limit=limit,
        offset=offset,
        from_date=from_date,
        to_date=to_date,
    )
    return report.to_api_dict()


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
