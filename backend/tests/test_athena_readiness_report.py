from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts.athena_readiness_report import build_report


def test_athena_readiness_report_is_read_only_and_conservative(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    report = build_report(
        database=database,
        as_of=datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "athena_readiness_diagnostics"
    assert report["automaticActivation"] is False
    assert report["marketUniverse"]["isGlobalReady"] is False
    assert report["marketWeighting"]["ready"] is False
    assert "external_market_cap_validation_required" in report["marketWeighting"][
        "blockers"
    ]
    assert report["instrumentTypes"]["listingCount"] == 0
    assert report["marketHistory"]["observationCount"] == 0
    assert report["marketHistory"]["instrumentCoverage"] == 0.0
    assert (
        report["recommendationLearning"]["automaticModelMutation"]
        is False
    )


def test_athena_readiness_report_requires_timezone_aware_as_of(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    with pytest.raises(ValueError, match="zona horaria"):
        build_report(
            database=database,
            as_of=datetime(2026, 9, 1, 21, 0),
        )
