from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts.evaluate_due_recommendations import parse_as_of, run


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
