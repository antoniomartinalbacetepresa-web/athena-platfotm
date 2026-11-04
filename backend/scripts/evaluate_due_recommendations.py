from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_outcome_evaluation_service import (
    RecommendationOutcomeEvaluationService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evalúa recomendaciones ATHENA vencidas usando exclusivamente "
            "observaciones de mercado point-in-time ya persistidas."
        )
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        help=(
            "Instante de corte ISO-8601 con zona horaria. Si se omite se usa "
            "la hora UTC actual."
        ),
    )
    parser.add_argument(
        "--require-complete", action="store_true",
        help="Sale con código 3 si alguna recomendación vencida no pudo medirse; cero vencidas no acredita evidencia OOS.",
    )
    return parser


def parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    normalized = value.strip()
    if not normalized:
        raise ValueError("--as-of no puede estar vacío.")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def validate_operational_cutoff(
    as_of: datetime, *, now: datetime | None = None,
) -> datetime:
    """Never backdate a new persisted evaluation to a historical PIT cutoff.

    This boundary applies to the mutating CLI. Historical research diagnostics
    must use read-only evidence rather than minting retroactive outcome rows.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("El corte operativo debe incluir zona horaria.")
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("El reloj operativo debe incluir zona horaria.")
    cutoff = as_of.astimezone(timezone.utc)
    current = current.astimezone(timezone.utc)
    if cutoff > current:
        raise ValueError("No se pueden persistir resultados con corte futuro.")
    if current - cutoff > timedelta(minutes=5):
        raise ValueError("No se pueden retrofechar resultados operativos.")
    return cutoff


def run(
    *,
    as_of: datetime,
    database: AthenaDatabase | None = None,
) -> dict[str, Any]:
    report = RecommendationOutcomeEvaluationService(
        database=database,
    ).evaluate_due(as_of=as_of)
    return report.to_api_dict()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cutoff = validate_operational_cutoff(parse_as_of(args.as_of))
    except ValueError:
        parser.exit(2, "Corte operativo inválido o retrospectivo; no se ha escrito ningún outcome.\n")
    report = run(as_of=cutoff)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.require_complete and (
        report.get("skippedCount") != 0
        or report.get("dueCount") != report.get("evaluatedCount")
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
