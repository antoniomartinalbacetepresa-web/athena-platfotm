from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from scripts.export_corporate_action_reconciliation import export_worklist


AS_OF = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _instrument(database: AthenaDatabase, symbol: str) -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) "
            "VALUES (?, ?, 'NASDAQ', 'common_stock')",
            (symbol, symbol),
        )
        return int(cursor.lastrowid)


def _dividend(
    database: AthenaDatabase, instrument_id: int, provider: str, amount: float,
    retrieved_at: datetime,
) -> None:
    CorporateActionRepository(database).save_many(
        instrument_id=instrument_id,
        source_provider=provider,
        retrieved_at=retrieved_at,
        actions=[{
            "type": "dividend",
            "effectiveAt": (AS_OF - timedelta(days=30)).isoformat(),
            "cashAmount": amount,
            "currency": "USD",
        }],
    )


def test_full_export_uses_read_only_consistent_snapshot_and_includes_conflicts(tmp_path) -> None:
    source = tmp_path / "source.db"
    database = AthenaDatabase(source)
    database.initialize()
    missing = _instrument(database, "MISSING")
    conflict = _instrument(database, "CONFLICT")
    agreed = _instrument(database, "AGREED")
    observed = AS_OF - timedelta(days=20)
    _dividend(database, missing, "yahoo", 0.25, observed)
    _dividend(database, conflict, "yahoo", 0.25, observed)
    _dividend(database, conflict, "alpha_vantage", 0.30, observed)
    _dividend(database, agreed, "yahoo", 0.25, observed)
    _dividend(database, agreed, "alpha_vantage", 0.25, observed)

    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "complete.jsonl"
    summary = export_worklist(database_path=source, output_path=output, as_of=AS_OF)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert summary["totalUnresolvedEventCount"] == 2
    assert summary["totalIncompleteEventCount"] == 1
    assert summary["totalConflictEventCount"] == 1
    assert summary["productionCoverageClaimed"] is False
    assert summary["exportSha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.stat().st_mode & 0o077 == 0

    lines = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(lines) == 3
    assert lines[0]["completeExport"] is True
    assert lines[0]["snapshotSha256"] == summary["snapshotSha256"]
    assert [(line["symbol"], line["reconciliationStatus"]) for line in lines[1:]] == [
        ("MISSING", "incomplete"), ("CONFLICT", "conflict")
    ]


def test_export_is_pit_and_refuses_overwriting_existing_evidence(tmp_path) -> None:
    source = tmp_path / "source.db"
    database = AthenaDatabase(source)
    database.initialize()
    instrument = _instrument(database, "PIT")
    _dividend(database, instrument, "yahoo", 0.25, AS_OF - timedelta(days=10))
    _dividend(database, instrument, "alpha_vantage", 0.25, AS_OF + timedelta(days=1))
    output = tmp_path / "report.jsonl"
    summary = export_worklist(database_path=source, output_path=output, as_of=AS_OF)
    assert summary["totalIncompleteEventCount"] == 1
    assert json.loads(output.read_text().splitlines()[1])["observedProviders"] == ["yahoo"]
    previous = output.read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        export_worklist(database_path=source, output_path=output, as_of=AS_OF)
    assert output.read_bytes() == previous


def test_export_rejects_invalid_source_or_naive_cutoff_without_output(tmp_path) -> None:
    output = tmp_path / "report.jsonl"
    with pytest.raises(ValueError, match="timezone"):
        export_worklist(
            database_path=tmp_path / "missing.db",
            output_path=output,
            as_of=datetime(2026, 10, 1),
        )
    with pytest.raises(FileNotFoundError, match="does not exist"):
        export_worklist(
            database_path=tmp_path / "missing.db",
            output_path=output,
            as_of=AS_OF,
        )
    assert not output.exists()
    assert not (tmp_path / "missing.db").exists()
