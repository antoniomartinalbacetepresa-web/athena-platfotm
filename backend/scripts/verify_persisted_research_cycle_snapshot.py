"""Read-only canonical verification of a checkpointed ATHENA research snapshot.

No migrations, model calls, writes, orders, or production claims. The snapshot
must be an independently copied, consistent SQLite database, NOT a live WAL DB.
The expected SHA-256 must come from a trusted backup manifest.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.recommendation_athena_synthesis import _canonical_hash, _cycle_evidence_contract, _input_contract
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
from app.repositories.recommendation_investors_synthesis_repository import RecommendationInvestorsSynthesisRepository
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository

_SHA = re.compile(r"^[0-9a-f]{64}$")
_TABLES = {
    "cycle": "athena_professional_research_cycles",
    "news": "athena_news_syntheses",
    "investors": "athena_investors_syntheses",
    "athena": "athena_research_syntheses",
}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_checkpointed(snapshot: Path) -> None:
    """An immutable SQLite reader ignores WAL, so sidecars must be absent.

    Otherwise the SHA-256 of the main database can match while committed
    changes live only in the WAL and are silently omitted from validation.
    """
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(snapshot) + suffix).exists():
            raise ValueError(
                "El snapshot no está aislado/checkpointed: existen archivos auxiliares SQLite."
            )


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field}: timestamp ISO obligatorio.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}: timestamp ISO inválido.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}: timezone obligatorio.")
    return parsed.astimezone(timezone.utc)


def verify(snapshot: Path, *, expected_sha256: str, cycle_hash: str) -> dict[str, object]:
    if not _SHA.fullmatch(expected_sha256) or not _SHA.fullmatch(cycle_hash):
        raise ValueError("Se requieren hashes SHA-256 hexadecimales en minúsculas.")
    snapshot = snapshot.expanduser().resolve(strict=True)
    if not snapshot.is_file():
        raise ValueError("El snapshot debe ser un archivo regular.")
    _assert_checkpointed(snapshot)
    if _file_hash(snapshot) != expected_sha256:
        raise ValueError("El SHA-256 del snapshot no coincide con el manifiesto.")
    cycle_repo = RecommendationProfessionalResearchCycleRepository()
    news_repo = RecommendationNewsSynthesisRepository()
    investors_repo = RecommendationInvestorsSynthesisRepository()
    athena_repo = RecommendationAthenaSynthesisRepository()
    # immutable=1 avoids WAL/shm sidecars; caller MUST supply a checkpointed copy.
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if _TABLES["cycle"] not in tables:
            raise ValueError("No existe la tabla de Research Cycle persistidos.")

        def fetch(kind: str) -> sqlite3.Row | None:
            table = _TABLES[kind]
            if table not in tables:
                return None
            return conn.execute(
                f"SELECT * FROM {table} WHERE cycle_hash = ? ORDER BY id DESC LIMIT 1",
                (cycle_hash,),
            ).fetchone()

        cycle_row = fetch("cycle")
        if cycle_row is None:
            raise ValueError("No existe el Research Cycle solicitado en el snapshot.")
        cycle = cycle_repo.validate_record(cycle_repo._row(cycle_row))
        contract = _cycle_evidence_contract(cycle)
        if contract["inputAsOf"] > datetime.now(timezone.utc):
            raise ValueError("El Research Cycle tiene un corte PIT futuro.")
        news = investors = None
        if contract["hasNews"]:
            news_row = fetch("news")
            if news_row is None:
                raise ValueError("Falta la síntesis News persistida requerida.")
            news = news_repo.validate_record(news_repo._row(news_row))
            if news["cycle_hash"] != cycle_hash or news["radar_hash"] != cycle["radar_hash"]:
                raise ValueError("La síntesis News no coincide con el ciclo/Radar.")
            radar_news = {
                item["evidenceId"]: (item["sourceRef"], item["availableAt"])
                for candidate in cycle["package"]["radar"]["candidates"]
                for item in candidate["evidence"] if item["category"].lower() == "news"
            }
            assessments = news["package"]["synthesis"]["assessments"]
            if {a["evidenceId"] for a in assessments} != set(radar_news):
                raise ValueError("La síntesis News no cubre exactamente las evidencias News del Radar.")
            for assessment in assessments:
                ref, available = radar_news[assessment["evidenceId"]]
                if assessment["sourceRef"] != ref or _utc(assessment["availableAt"], "news.availableAt") != _utc(available, "radar.availableAt"):
                    raise ValueError("La provenance News no coincide con el Radar persistido.")
                generated = _utc(assessment["generatedAt"], "news.generatedAt")
                if generated < _utc(available, "radar.availableAt") or generated > contract["inputAsOf"]:
                    raise ValueError("La generación News está fuera del intervalo PIT.")
        if contract["hasInvestors"]:
            investors_row = fetch("investors")
            if investors_row is None:
                raise ValueError("Falta la síntesis Investors persistida requerida.")
            investors = investors_repo.validate_record(investors_repo._row(investors_row))
            if investors["cycle_hash"] != cycle_hash or investors["radar_hash"] != cycle["radar_hash"]:
                raise ValueError("La síntesis Investors no coincide con el ciclo/Radar.")
        input_contract = _input_contract(cycle, news, investors, contract)
        athena_row = fetch("athena")
        existing_athena = athena_row is not None
        if athena_row is not None:
            # A row's existence alone is not proof of a valid, canonical
            # artifact. Reject corrupt/retrospectively substituted outputs.
            persisted = athena_repo.validate_record(athena_repo._row(athena_row))
            stored = persisted["package"]["synthesis"]
            expected_news = news["synthesis_hash"] if news else None
            expected_investors = investors["synthesis_hash"] if investors else None
            if (
                persisted["cycle_hash"] != cycle_hash
                or persisted["radar_hash"] != cycle["radar_hash"]
                or persisted["news_synthesis_hash"] != expected_news
                or stored.get("investorsSynthesisHash") != expected_investors
                or stored.get("inputFingerprint") != input_contract["inputFingerprint"]
                or _utc(stored.get("inputAsOf"), "athena.inputAsOf") != contract["inputAsOf"]
                or _utc(stored.get("generatedAt"), "athena.generatedAt") < contract["inputAsOf"]
                or set(stored.get("evidenceIds", [])) != set(contract["evidenceIds"])
                or set(stored.get("coveredCategories", [])) != set(contract["coveredCategories"])
            ):
                raise ValueError("La ATHENA synthesis persistida no coincide con el contrato canónico.")
            expected_output = _canonical_hash({
                "inputFingerprint": input_contract["inputFingerprint"],
                "modelProvider": stored["modelProvider"],
                "modelName": stored["modelName"],
                "modelVersion": stored["modelVersion"],
                "generatedAt": stored["generatedAt"],
                "summary": stored["summary"],
                "rationale": stored["rationale"],
                "uncertainties": stored["uncertainties"],
                "evidenceIds": stored["evidenceIds"],
                "investorsSynthesisHash": expected_investors,
            })
            if stored.get("outputFingerprint") != expected_output:
                raise ValueError("El outputFingerprint ATHENA no coincide con la síntesis persistida.")

    # Detect auxiliary journals or main-file changes during verification.
    _assert_checkpointed(snapshot)
    if _file_hash(snapshot) != expected_sha256:
        raise ValueError("El snapshot cambió durante la verificación.")
    return {
        "status": "canonical_snapshot_dependencies_verified",
        "snapshotSha256": expected_sha256,
        "cycleHash": cycle_hash,
        "radarHash": cycle["radar_hash"],
        "newsSynthesisHash": news["synthesis_hash"] if news else None,
        "investorsSynthesisHash": investors["synthesis_hash"] if investors else None,
        "snapshotDerivedInputFingerprint": input_contract["inputFingerprint"],
        "evidenceCount": len(contract["evidenceIds"]),
        "categories": list(contract["coveredCategories"]),
        "athenaAlreadyPersisted": existing_athena,
        "persistedAthenaIntegrityVerified": existing_athena,
        "readyForNewLocalDraft": not existing_athena,
        "sourceAuthenticityIndependentlyVerified": False,
        "modelExecutionVerified": False,
        "productionEligible": False,
        "automaticTrading": False,
        "interpretation": "snapshot_only_must_match_deployed_input_contract_before_any_persistence",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--cycle-hash", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.snapshot, expected_sha256=args.expected_sha256, cycle_hash=args.cycle_hash)
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        # No raw database paths, records, or secrets in error output.
        print(json.dumps({"status": "blocked", "reason": type(exc).__name__,
                          "detail": str(exc) if isinstance(exc, ValueError) else "No se pudo leer el snapshot."},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
