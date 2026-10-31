from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from app.services.incident_response_readiness_service import (
    IncidentResponseEvidence,
    IncidentResponseReadinessService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evalúa evidencia operacional explícita de respuesta a incidentes "
            "sin convertir CI, fixtures o configuración en evidencia de producción."
        )
    )
    parser.add_argument("--evidence", type=Path, required=True)
    return parser


def _required_bool(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} debe ser booleano explícito.")
    return value


def _optional_timestamp(payload: dict[str, Any], name: str) -> datetime | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser ISO-8601 o null.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} no es un timestamp ISO-8601 válido.") from exc


def evaluate_evidence_file(
    evidence_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = evidence_path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("La evidencia debe ser un objeto JSON.")

    evidence = IncidentResponseEvidence(
        runbook_reviewed_at=_optional_timestamp(payload, "runbookReviewedAt"),
        exercise_completed_at=_optional_timestamp(payload, "exerciseCompletedAt"),
        incident_owner_assigned=_required_bool(payload, "incidentOwnerAssigned"),
        escalation_channel_verified=_required_bool(payload, "escalationChannelVerified"),
        credential_revocation_procedure_verified=_required_bool(
            payload, "credentialRevocationProcedureVerified"
        ),
        recovery_procedure_verified=_required_bool(
            payload, "recoveryProcedureVerified"
        ),
    )
    return IncidentResponseReadinessService().evaluate(evidence, now=now).to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = evaluate_evidence_file(args.evidence)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
