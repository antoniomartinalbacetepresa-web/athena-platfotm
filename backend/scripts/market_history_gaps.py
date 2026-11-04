from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.market_history_gap_service import MarketHistoryGapService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lista instrumentos elegibles que todavía no cumplen el mínimo de "
            "365 días continuos dentro de una sola fuente."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MarketHistoryGapService.DEFAULT_LIMIT,
        help=(
            "Máximo de bloqueos a devolver por página "
            f"(por defecto {MarketHistoryGapService.DEFAULT_LIMIT}, "
            f"máximo {MarketHistoryGapService.MAX_LIMIT})."
        ),
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Desplazamiento dentro de la cola de bloqueos priorizada.",
    )
    return parser


def run(*, limit: int, offset: int) -> dict[str, Any]:
    return MarketHistoryGapService().get_report(limit=limit, offset=offset).to_api_dict()


def main() -> None:
    args = build_parser().parse_args()
    print(
        json.dumps(
            run(limit=args.limit, offset=args.offset),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
