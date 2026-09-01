from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app.services.yahoo_regional_universe_source import (
    YahooRegionalUniverseSource,
)
from scripts.import_yahoo_regional_universe import run_import


DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES_PER_REGION = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresca el universo ponderable de ATHENA TYCHE con equities "
            "regionales de Yahoo y devuelve un informe de cobertura."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--regions",
        default=",".join(YahooRegionalUniverseSource.DEFAULT_REGIONS),
        help=(
            "Regiones Yahoo separadas por comas. Por defecto incluye EE. UU., "
            "Europa, Asia y principales mercados de América."
        ),
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Resultados por región (1-250).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_REGION,
        help="Máximo de páginas por región.",
    )
    return parser


def _normalize_regions(value: str) -> tuple[str, ...]:
    regions = tuple(
        part.strip().lower()
        for part in value.split(",")
        if part.strip()
    )
    if not regions:
        raise ValueError("Debe indicarse al menos una región.")
    return regions


def run_refresh(
    *,
    database_path: Path | None = None,
    regions: tuple[str, ...] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES_PER_REGION,
    importer: Callable[..., dict[str, object]] = run_import,
) -> dict[str, object]:
    selected_regions = regions or YahooRegionalUniverseSource.DEFAULT_REGIONS

    result = importer(
        database_path=database_path,
        regions=selected_regions,
        page_size=page_size,
        max_pages=max_pages,
    )

    quality = result.get("catalogQuality")
    if not isinstance(quality, dict):
        raise RuntimeError(
            "El refresco no devolvió un informe de calidad del catálogo."
        )

    return {
        "status": "ready" if quality.get("isGlobalReady") else "fallback",
        "source": result.get("source"),
        "regions": list(selected_regions),
        "received": result.get("received"),
        "accepted": result.get("accepted"),
        "rejected": result.get("rejected"),
        "inserted": result.get("inserted"),
        "updated": result.get("updated"),
        "unchanged": result.get("unchanged"),
        "activeSourceMemberships": result.get("activeSourceMemberships"),
        "catalogQuality": quality,
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        regions = _normalize_regions(args.regions)
        result = run_refresh(
            database_path=args.database,
            regions=regions,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
