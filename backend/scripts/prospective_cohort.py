"""Manual prospective ledger operations; supplied coverage refs are not outcomes.

Run from backend with PYTHONPATH=. python scripts/prospective_cohort.py --help.
Database selection uses the existing ATHENA_DATABASE_PATH configuration.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

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
    measured = commands.add_parser("measured", help="Mide errores y outcomes realmente persistidos; no acredita fuentes externas.")
    measured.add_argument("--cohort-id", required=True)
    measured.add_argument("--expected-cohort-hash", help="Pin de la selección prospectiva.")
    measured.add_argument("--as-of", required=True, help="Corte ISO-8601 con zona horaria.")
    measured.add_argument("--require-complete-measurement", action="store_true",
                          help="Sale con código 3 salvo que toda la selección haya vencido y tenga errores y outcomes persistidos.")
    return parser


def _complete_measured_evidence(report: dict) -> bool:
    """Strict descriptive-completeness gate, never a skill or production gate."""
    if not isinstance(report, dict):
        return False
    selected = report.get("selectedCount")
    matured = report.get("maturedCount")
    measured = report.get("measuredErrorCount")
    statistics = report.get("observedErrorStatistics")
    return (
        type(selected) is int and selected > 0
        and type(matured) is int and matured == selected
        and type(measured) is int and measured == selected
        and report.get("missingMaturedSpecificationHashes") == []
        and report.get("membershipComplete") is True
        and report.get("persistedOutcomeChainVerified") is True
        and report.get("errorStorePresent") is True
        and report.get("maturedMeasurementCoverage") == 1.0
        and isinstance(statistics, dict)
        and type(statistics.get("sampleCount")) is int
        and statistics["sampleCount"] == selected
        and statistics.get("descriptiveOnly") is True
        and all(report.get(flag) is False for flag in (
            "independentMarketSourceVerified", "predictiveSkillEstablished",
            "outcomeEvidenceVerified", "productionEligible",
            "productionLearningEligible", "automaticTrading",
        ))
    )


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
    if args.command == "measured":
        normalized = args.as_of.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        cutoff = datetime.fromisoformat(normalized)
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("--as-of requiere zona horaria.")
        if cutoff.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise ValueError("--as-of no puede ser futuro.")
        result = ledger.measured_coverage(cohort_id=args.cohort_id, as_of=cutoff.astimezone(timezone.utc))
        if expected is not None and result.get("cohortHash") != expected:
            raise ValueError("La medición no coincide con el pin esperado.")
        return result
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
    if args.command == "measured" and args.require_complete_measurement:
        return 0 if _complete_measured_evidence(result) else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
