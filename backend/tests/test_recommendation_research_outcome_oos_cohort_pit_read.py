from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_research_outcome_oos_cohort_repository import (
    RecommendationResearchOutcomeOosCohortRepository,
)


class _PassThroughService:
    def validate_artifact(self, artifact):
        return artifact


def _artifact(*, cohort_id: str, cohort_hash: str, as_of: str):
    return {
        "cohortId": cohort_id,
        "cohortHash": cohort_hash,
        "asOf": as_of,
        "observationCount": 1,
        "distinctResolvedIssuerCount": 1,
        "horizonCount": 1,
    }


def test_latest_oos_cohort_read_respects_pit_cutoff(tmp_path: Path) -> None:
    repository = RecommendationResearchOutcomeOosCohortRepository(
        AthenaDatabase(tmp_path / "oos-pit.db"),
        _PassThroughService(),
    )
    first = _artifact(
        cohort_id="cohort-first",
        cohort_hash="a" * 64,
        as_of="2026-01-31T12:00:00+00:00",
    )
    future = _artifact(
        cohort_id="cohort-future",
        cohort_hash="b" * 64,
        as_of="2026-03-31T12:00:00+00:00",
    )
    repository.append(artifact=first)
    repository.append(artifact=future)
    # The fixtures represent cohorts actually persisted at their historical
    # cutoffs; append() itself correctly stamps the current wall-clock time.
    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_outcome_oos_cohorts SET created_at = as_of"
        )

    before_all = repository.get_latest_at_or_before(
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    between = repository.get_latest_at_or_before(
        as_of=datetime(2026, 2, 15, tzinfo=timezone.utc)
    )
    after_all = repository.get_latest_at_or_before(
        as_of=datetime(2026, 4, 1, tzinfo=timezone.utc)
    )

    assert before_all is None
    assert between is not None
    assert between["cohort_hash"] == "a" * 64
    assert after_all is not None
    assert after_all["cohort_hash"] == "b" * 64


def test_latest_oos_cohort_read_rejects_naive_cutoff(tmp_path: Path) -> None:
    repository = RecommendationResearchOutcomeOosCohortRepository(
        AthenaDatabase(tmp_path / "oos-pit-naive.db"),
        _PassThroughService(),
    )

    with pytest.raises(ValueError, match="zona horaria"):
        repository.get_latest_at_or_before(as_of=datetime(2026, 1, 1))



def test_backfilled_cohort_is_invisible_until_its_actual_persistence_instant(tmp_path: Path) -> None:
    repository = RecommendationResearchOutcomeOosCohortRepository(
        AthenaDatabase(tmp_path / "oos-backfill-pit.db"),
        _PassThroughService(),
    )
    artifact = _artifact(
        cohort_id="late-backfill",
        cohort_hash="c" * 64,
        as_of="2026-01-31T12:00:00+00:00",
    )
    repository.append(artifact=artifact)
    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_outcome_oos_cohorts SET created_at = ?",
            ("2026-04-01T10:00:00-05:00",),
        )

    assert repository.get_latest_at_or_before(
        as_of=datetime.fromisoformat("2026-04-01T14:59:59.999999+00:00")
    ) is None
    visible = repository.get_latest_at_or_before(
        as_of=datetime.fromisoformat("2026-04-01T15:00:00+00:00")
    )
    assert visible is not None
    assert visible["cohort_hash"] == "c" * 64


def test_cohort_pit_read_uses_instant_order_not_iso_text_order(tmp_path: Path) -> None:
    repository = RecommendationResearchOutcomeOosCohortRepository(
        AthenaDatabase(tmp_path / "oos-offset-pit.db"),
        _PassThroughService(),
    )
    artifact = _artifact(
        cohort_id="offset-cohort",
        cohort_hash="d" * 64,
        as_of="2026-03-01T00:30:00+02:00",
    )
    repository.append(artifact=artifact)
    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_outcome_oos_cohorts SET created_at = ?",
            ("2026-02-28T22:30:00+00:00",),
        )
    visible = repository.get_latest_at_or_before(
        as_of=datetime.fromisoformat("2026-02-28T23:00:00+00:00")
    )
    assert visible is not None
    assert visible["cohort_hash"] == "d" * 64


def test_cohort_pit_read_rejects_unverifiable_persistence_time(tmp_path: Path) -> None:
    repository = RecommendationResearchOutcomeOosCohortRepository(
        AthenaDatabase(tmp_path / "oos-invalid-pit.db"),
        _PassThroughService(),
    )
    repository.append(artifact=_artifact(
        cohort_id="bad-time", cohort_hash="e" * 64,
        as_of="2026-01-31T12:00:00+00:00",
    ))
    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_outcome_oos_cohorts SET created_at = ?",
            ("2026-01-31T12:00:00",),
        )
    with pytest.raises(ValueError, match="zona horaria"):
        repository.get_latest_at_or_before(
            as_of=datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
