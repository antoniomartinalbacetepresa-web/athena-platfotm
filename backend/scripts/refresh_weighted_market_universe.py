from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app.database.athena_database import AthenaDatabase
from app.services.market_cap_coverage_service import MarketCapCoverageService
from app.services.yahoo_regional_universe_source import (
    YahooRegionalUniverseSource,
)
from scripts.import_yahoo_regional_universe import run_import


DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES_PER_REGION = 1
EXHAUSTIVE_PAGE_SIZE = 250


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresca el universo ponderable de ATHENA TYCHE con equities "
            "regionales de Yahoo y devuelve informes de cobertura y "
            "concentración de capitalización."
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
        help="Máximo de páginas por región cuando no se usa --exhaustive.",
    )
    parser.add_argument(
        "--exhaustive",
        action="store_true",
        help=(
            "Usa páginas de 250 y continúa hasta agotar los resultados "
            "disponibles de cada mercado."
        ),
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


def _build_capitalization_profile(database_path: Path | None) -> dict[str, object]:
    database = AthenaDatabase(database_path)
    return (
        MarketCapCoverageService(database=database)
        .get_report()
        .to_api_dict()
    )


def run_refresh(
    *,
    database_path: Path | None = None,
    regions: tuple[str, ...] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = DEFAULT_MAX_PAGES_PER_REGION,
    importer: Callable[..., dict[str, object]] = run_import,
    profile_builder: Callable[[Path | None], dict[str, object]] = (
        _build_capitalization_profile
    ),
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

    capitalization_profile = profile_builder(database_path)

    return {
        "status": "ready" if quality.get("isGlobalReady") else "fallback",
        "source": result.get("source"),
        "regions": list(selected_regions),
        "pageSize": page_size,
        "maxPagesPerRegion": max_pages,
        "exhaustive": max_pages is None,
        "received": result.get("received"),
        "accepted": result.get("accepted"),
        "rejected": result.get("rejected"),
        "inserted": result.get("inserted"),
        "updated": result.get("updated"),
        "unchanged": result.get("unchanged"),
        "activeSourceMemberships": result.get("activeSourceMemberships"),
        "catalogQuality": quality,
        "capitalizationProfile": capitalization_profile,
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        regions = _normalize_regions(args.regions)
        exhaustive = bool(args.exhaustive)
        result = run_refresh(
            database_path=args.database,
            regions=regions,
            page_size=EXHAUSTIVE_PAGE_SIZE if exhaustive else args.page_size,
            max_pages=None if exhaustive else args.max_pages,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
