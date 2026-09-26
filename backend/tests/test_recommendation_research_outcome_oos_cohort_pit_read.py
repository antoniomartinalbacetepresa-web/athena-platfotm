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
