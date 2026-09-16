from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.canonical_weighting_governance_service import (
    CanonicalWeightingGovernanceService,
)


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
        help="Devuelve únicamente el último weighting con aprobación humana; falla cerrado si no existe.",
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


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run(args), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
