"""Manual prospective ledger operations; supplied coverage refs are not outcomes.

Run from backend with PYTHONPATH=. python scripts/prospective_cohort.py --help.
Database selection uses the existing ATHENA_DATABASE_PATH configuration.
"""
from __future__ import annotations

import argparse
import json
import re

from app.services.recommendation_research_prospective_cohort_service import (
    RecommendationResearchProspectiveCohortService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ledger prospectivo manual, sin promoción ni trading.")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="Congela forecasts v3 observados antes de sus periodos.")
    register.add_argument("--cohort-id", required=True)
    register.add_argument("--specification-hash", action="append", required=True)
    show = commands.add_parser("show", help="Revalida selección, inputs y recibos persistidos.")
    show.add_argument("--cohort-id", required=True)
    show.add_argument("--expected-cohort-hash", help="Pin opcional de la selección sellada esperada.")
    coverage = commands.add_parser("coverage", help="Contabilidad de referencias, no evidencia de outcomes.")
    coverage.add_argument("--cohort-id", required=True)
    coverage.add_argument("--expected-cohort-hash", help="Pin opcional de la selección sellada esperada.")
    coverage.add_argument("--evaluated-specification-hash", action="append", default=[])
    return parser


def run(args: argparse.Namespace, *, service=None) -> dict:
    ledger = service if service is not None else RecommendationResearchProspectiveCohortService()
    expected = getattr(args, "expected_cohort_hash", None)
    if expected is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Pin de cohorte inválido.")
        original = ledger.get(cohort_id=args.cohort_id)
        if original.get("cohortHash") != expected:
            raise ValueError("La selección persistida no coincide con el pin esperado.")
    if args.command == "register":
        return ledger.register(cohort_id=args.cohort_id, specification_hashes=args.specification_hash)
    if args.command == "show":
        return original if expected is not None else ledger.get(cohort_id=args.cohort_id)
    if args.command == "coverage":
        result = ledger.coverage(cohort_id=args.cohort_id,
                                 evaluated_specification_hashes=args.evaluated_specification_hash)
        if expected is not None and result.get("cohortHash") != expected:
            raise ValueError("La cobertura no coincide con la selección esperada.")
        return result
    raise ValueError("Operación de cohorte desconocida.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
        serialized = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except Exception:
        # Do not leak storage details or partially validated evidence.
        parser.exit(1, "No se pudo verificar la operación prospectiva; no se concede autoridad productiva.\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
