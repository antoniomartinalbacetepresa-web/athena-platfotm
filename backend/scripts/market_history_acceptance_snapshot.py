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
from contextlib import closing
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
    blocker_limit: int = 100,
    blocker_offset: int = 0,
) -> dict[str, Any]:
    """Measure one consistent SQLite snapshot without modifying the source."""
    if (
        isinstance(blocker_limit, bool)
        or not isinstance(blocker_limit, int)
        or not 1 <= blocker_limit <= MarketHistoryGapService.MAX_LIMIT
    ):
        raise ValueError("blocker_limit debe estar entre 1 y 1000.")
    if isinstance(blocker_offset, bool) or not isinstance(blocker_offset, int) or blocker_offset < 0:
        raise ValueError("blocker_offset debe ser un entero no negativo.")
    source_path = Path(database_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError("La base SQLite indicada no existe.")
    cutoff = as_of if as_of is not None else datetime.now(timezone.utc)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("as_of debe incluir zona horaria.")
    cutoff = cutoff.astimezone(timezone.utc)
    # A diagnostic for a future instant cannot substantiate observed PIT coverage.
    if cutoff > datetime.now(timezone.utc):
        raise ValueError("as_of no puede ser una fecha futura.")

    with tempfile.TemporaryDirectory(prefix="athena-history-snapshot-") as directory:
        snapshot_path = Path(directory) / "market-history.db"
        # URI mode=ro prevents creation or modification of the source database.
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot_path)) as snapshot:
                source.backup(snapshot)
        # Fingerprint the exact backed-up source image, before any migrations
        # performed against the disposable copy.
        digest = hashlib.sha256()
        with snapshot_path.open("rb") as copied_file:
            for chunk in iter(lambda: copied_file.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint = digest.hexdigest()

        # A successful backup is not evidence that every SQLite page is valid.
        # Check the unmodified copy before schema initialization or diagnostics.
        with closing(sqlite3.connect(snapshot_path)) as snapshot:
            integrity = snapshot.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("La copia SQLite no supera la comprobación de integridad.")

        database = AthenaDatabase(snapshot_path)
        coverage = MarketObservationCoverageService(database=database).get_report(
            as_of=cutoff
        )
        gaps = MarketHistoryGapService(database=database).get_report(
            as_of=cutoff, limit=blocker_limit, offset=blocker_offset
        )

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
        "blockingPage": {
            "limit": blocker_limit,
            "offset": blocker_offset,
            "returnedCount": len(gaps.items),
            "hasMore": blocker_offset + len(gaps.items) < blocked,
        },
        "blockingItems": [item.to_api_dict() for item in gaps.items],
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
    parser.add_argument(
        "--blocker-limit", type=int, default=100,
        help="Máximo de bloqueos concretos en la página (1..1000).",
    )
    parser.add_argument(
        "--blocker-offset", type=int, default=0,
        help="Desplazamiento de la página de bloqueos (>=0).",
    )
    args = parser.parse_args()
    try:
        cutoff = parse_cutoff(args.as_of) if args.as_of else None
        result = run_snapshot(
            args.database, as_of=cutoff,
            blocker_limit=args.blocker_limit, blocker_offset=args.blocker_offset,
        )
    except (FileNotFoundError, ValueError, sqlite3.Error, RuntimeError) as exc:
        parser.exit(2, f"Diagnóstico no disponible: {type(exc).__name__}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
