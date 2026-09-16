from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.canonical_weighting_governance_service import (
    CanonicalWeightingGovernanceService,
)


_BLOCKED_CURRENT_STATUSES = {
    "blocked_pending_human_approval",
    "blocked_stale_evidence_requires_human_approval",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Gobierno manual del weighting canónico. Crear una propuesta nunca la activa; "
            "approve/reject requieren una decisión humana explícita y quedan auditados."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose", help="Crea una propuesta pendiente, sin aprobarla.")
    propose.add_argument("--created-by", required=True)

    approve = subparsers.add_parser("approve", help="Registra aprobación humana explícita.")
    approve.add_argument("--proposal-id", required=True, type=int)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--note", required=True)

    reject = subparsers.add_parser("reject", help="Registra rechazo humano explícito.")
    reject.add_argument("--proposal-id", required=True, type=int)
    reject.add_argument("--rejected-by", required=True)
    reject.add_argument("--note", required=True)

    show = subparsers.add_parser("show", help="Muestra una propuesta por id.")
    show.add_argument("--proposal-id", required=True, type=int)

    subparsers.add_parser(
        "current",
        help=(
            "Devuelve únicamente el último weighting con aprobación humana; "
            "termina con código distinto de cero si el gate está bloqueado."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    database = AthenaDatabase(args.database)
    service = CanonicalWeightingGovernanceService(database=database)

    if args.command == "propose":
        return service.create_proposal(created_by=args.created_by).to_api_dict()
    if args.command == "approve":
        return service.approve_proposal(
            args.proposal_id,
            approved_by=args.approved_by,
            approval_note=args.note,
        ).to_api_dict()
    if args.command == "reject":
        return service.reject_proposal(
            args.proposal_id,
            rejected_by=args.rejected_by,
            rejection_note=args.note,
        ).to_api_dict()
    if args.command == "show":
        return service.get_proposal(args.proposal_id).to_api_dict()
    if args.command == "current":
        return service.get_approved_weights()
    raise ValueError(f"Comando no soportado: {args.command}")


def exit_code_for_result(command: str, result: dict[str, object]) -> int:
    """Expose the governance gate to shell automation without bypassing humans.

    A JSON payload saying that weighting is blocked must not be accompanied by a
    successful process exit code: schedulers and release gates commonly consume
    only the exit status. Non-`current` commands are actions/diagnostics rather
    than readiness assertions and keep their normal success semantics.
    """

    if command != "current":
        return 0
    status = str(result.get("status") or "").strip()
    if status == "human_approved":
        return 0
    if status in _BLOCKED_CURRENT_STATUSES:
        return 2
    return 3


def main() -> int:
    args = build_parser().parse_args()
    result = run(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code_for_result(args.command, result)


if __name__ == "__main__":
    raise SystemExit(main())
