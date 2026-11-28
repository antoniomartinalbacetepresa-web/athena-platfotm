from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
import scripts.evaluate_due_recommendations as evaluation_cli
from scripts.evaluate_due_recommendations import parse_as_of, run, validate_operational_cutoff


def test_parse_as_of_normalizes_zulu_time_to_utc() -> None:
    parsed = parse_as_of("2026-09-01T20:30:00Z")

    assert parsed == datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)


def test_parse_as_of_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        parse_as_of("2026-09-01T20:30:00")


def test_run_is_safe_when_no_recommendations_are_due(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()

    report = run(
        as_of=datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc),
        database=database,
    )

    assert report["status"] == "point_in_time_evaluation"
    assert report["dueCount"] == 0
    assert report["evaluatedCount"] == 0
    assert report["skippedCount"] == 0
    assert report["benchmarkStatus"] == (
        "evaluated_when_explicit_frozen_benchmark_is_resolvable"
    )


def test_operational_cli_cutoff_rejects_future_and_backdated_persistence() -> None:
    now = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
    assert validate_operational_cutoff(now - timedelta(minutes=4), now=now) == (
        now - timedelta(minutes=4)
    )
    with pytest.raises(ValueError, match="futuro"):
        validate_operational_cutoff(now + timedelta(microseconds=1), now=now)
    with pytest.raises(ValueError, match="retrofechar"):
        validate_operational_cutoff(now - timedelta(minutes=5, seconds=1), now=now)
    with pytest.raises(ValueError, match="zona horaria"):
        validate_operational_cutoff(now.replace(tzinfo=None), now=now)


def test_operational_cli_does_not_write_when_cutoff_is_backdated(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(evaluation_cli, "run", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(SystemExit) as error:
        evaluation_cli.main(["--as-of", "2020-01-01T00:00:00Z"])
    assert error.value.code == 2
    assert calls == []


def test_operational_cli_complete_gate_detects_unmeasured_due_rows(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(evaluation_cli, "run", lambda **kwargs: {
        "dueCount": 2, "evaluatedCount": 1, "skippedCount": 1,
    })
    assert evaluation_cli.main(["--require-complete"]) == 3
    assert '"skippedCount": 1' in capsys.readouterr().out
    # Preserve the non-strict interactive CLI contract.
    assert evaluation_cli.main([]) == 0
