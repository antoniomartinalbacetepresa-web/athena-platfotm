from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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


def run(
    *,
    as_of: datetime,
    database: AthenaDatabase | None = None,
) -> dict[str, Any]:
    report = RecommendationOutcomeEvaluationService(
        database=database,
    ).evaluate_due(as_of=as_of)
    return report.to_api_dict()


def main() -> None:
    args = build_parser().parse_args()
    report = run(as_of=parse_as_of(args.as_of))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
