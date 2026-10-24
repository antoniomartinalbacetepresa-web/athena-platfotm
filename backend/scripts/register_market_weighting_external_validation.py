from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.market_weighting_external_validation_repository import (
    MarketWeightingExternalValidationRepository,
)
from app.services.market_weighting_readiness_service import MarketWeightingReadinessService


_EXTERNAL_BLOCKER = "external_market_cap_validation_required"


def register_validation(
    *,
    reference: str,
    reviewer_id: str,
    human_review_confirmed: bool,
    database: AthenaDatabase | None = None,
) -> dict[str, object]:
    db = database if database is not None else AthenaDatabase()
    service = MarketWeightingReadinessService(database=db)
    report = service.get_report()

    structural_blockers = tuple(
        blocker for blocker in report.blockers if blocker != _EXTERNAL_BLOCKER
    )
    if structural_blockers:
        raise RuntimeError(
            "No se puede registrar validación externa mientras existan bloqueos "
            f"estructurales: {', '.join(structural_blockers)}"
        )
    if not report.identity_evidence_fingerprint:
        raise RuntimeError("No existe fingerprint verificable de la evidencia de identidad.")

    repository = MarketWeightingExternalValidationRepository(database=db)
    return repository.register(
        identity_evidence_fingerprint=report.identity_evidence_fingerprint,
        reference=reference,
        reviewer_id=reviewer_id,
        human_review_confirmed=human_review_confirmed,
        validated_at=datetime.now(timezone.utc),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Registra de forma append-only una validación humana externa del "
            "universo canónico usado para pesos regionales. No activa pesos ni trading."
        )
    )
    parser.add_argument("--reference", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument(
        "--confirm-human-review",
        action="store_true",
        required=True,
        help="Confirma que la referencia fue revisada por una persona.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = register_validation(
        reference=args.reference,
        reviewer_id=args.reviewer_id,
        human_review_confirmed=args.confirm_human_review,
    )
    print(
        json.dumps(
            artifact,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
