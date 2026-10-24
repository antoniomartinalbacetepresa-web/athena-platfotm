"""Read-only, PIT-aligned historical acceptance snapshot for an explicit SQLite DB.

This diagnostic never certifies production coverage or authorizes trading.
The live SQLite database is opened read-only and backed up to a temporary copy;
ATHENA's schema initialization and queries run only against that copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService


def parse_cutoff(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as-of debe ser una fecha ISO 8601 válida.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as-of debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def run_snapshot(
    database_path: Path,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Measure one consistent SQLite snapshot without modifying the source."""
    source_path = Path(database_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError("La base SQLite indicada no existe.")
    cutoff = as_of if as_of is not None else datetime.now(timezone.utc)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("as_of debe incluir zona horaria.")
    cutoff = cutoff.astimezone(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="athena-history-snapshot-") as directory:
        snapshot_path = Path(directory) / "market-history.db"
        # URI mode=ro prevents creation or modification of the source database.
        with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot_path) as snapshot:
                source.backup(snapshot)

        database = AthenaDatabase(snapshot_path)
        coverage = MarketObservationCoverageService(database=database).get_report(
            as_of=cutoff
        )
        gaps = MarketHistoryGapService(database=database).get_report(
            as_of=cutoff, limit=1
        )
        fingerprint = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    eligible = coverage.history_eligible_instrument_count
    current = coverage.current_deep_history_instrument_count
    blocked = gaps.total_blocking_count
    reason_counts = gaps.to_api_dict()["blockingByReason"]
    if (
        eligible < 0
        or current < 0
        or blocked < 0
        or current > eligible
        or blocked > eligible
        or current + blocked != eligible
        or sum(reason_counts.values()) != blocked
        or coverage.minimum_history_days != gaps.minimum_history_days
        or coverage.maximum_source_gap_days != gaps.maximum_source_gap_days
        or coverage.as_of != gaps.as_of
    ):
        raise RuntimeError("Diagnósticos PIT de cobertura y bloqueos inconsistentes.")

    return {
        "status": "diagnostic_only",
        "asOf": cutoff.isoformat(),
        "snapshotSha256": fingerprint,
        "activeInstrumentCount": coverage.active_instrument_count,
        "historyEligibleInstrumentCount": eligible,
        "currentDeepHistoryInstrumentCount": current,
        "currentDeepHistoryCoverage": coverage.current_deep_history_coverage,
        "totalBlockingCount": blocked,
        "blockingByReason": reason_counts,
        "minimumHistoryDays": coverage.minimum_history_days,
        "maximumSourceGapDays": coverage.maximum_source_gap_days,
        "bySource": coverage.to_api_dict()["bySource"],
        "diagnosticReady": bool(
            eligible > 0
            and coverage.current_history_depth_ready
            and current == eligible
            and blocked == 0
        ),
        "productionCoverageClaimed": False,
        "operationalEvidenceVerified": False,
        "warning": (
            "Medición de una copia consistente de la base SQLite indicada, "
            "no verificación de origen productivo ni autorización de producción. "
            "El universo elegible corresponde al catálogo activo de la copia, "
            "no a una reconstrucción histórica de altas y bajas. "
            "Sin órdenes, weighting automático ni backfill."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, required=True,
        help="Ruta explícita a una base SQLite existente (se abre solo lectura).",
    )
    parser.add_argument(
        "--as-of", type=str,
        help="Corte PIT ISO 8601 con zona horaria (por defecto UTC actual).",
    )
    args = parser.parse_args()
    try:
        cutoff = parse_cutoff(args.as_of) if args.as_of else None
        result = run_snapshot(args.database, as_of=cutoff)
    except (FileNotFoundError, ValueError, sqlite3.Error, RuntimeError) as exc:
        parser.exit(2, f"Diagnóstico no disponible: {type(exc).__name__}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
