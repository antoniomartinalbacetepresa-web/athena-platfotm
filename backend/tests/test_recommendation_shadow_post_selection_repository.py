from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_post_selection_repository import (
    RecommendationShadowPostSelectionRepository,
)


def _model(*, research_cutoff: datetime) -> dict:
    return {
        "status": "shadow_model_frozen",
        "artifactVersion": "shadow-frozen-linear-v1",
        "featureSchemaVersion": "shadow-evidence-v1",
        "researchCutoff": research_cutoff.isoformat(),
        "horizonDays": 30,
        "ridgeLambda": 1.0,
        "features": ["technicalScore"],
        "medians": {"technicalScore": 0.0},
        "means": [0.0],
        "scales": [1.0],
        "intercept": 0.0,
        "coefficients": [0.1],
        "researchRowCount": 30,
        "fingerprint": "a" * 64,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_first_selection_boundary_is_immutable(tmp_path):
    repo = RecommendationShadowPostSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    model = _model(research_cutoff=cutoff)
    first_time = cutoff + timedelta(days=10)
    later_time = cutoff + timedelta(days=40)

    first = repo.register(frozen_model=model, selected_at=first_time)
    second = repo.register(frozen_model=model, selected_at=later_time)

    assert first["selection_fingerprint"] == second["selection_fingerprint"]
    assert first["selected_at"] == first_time.isoformat()
    assert second["selected_at"] == first_time.isoformat()


def test_selection_must_be_after_research_cutoff(tmp_path):
    repo = RecommendationShadowPostSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="posterior"):
        repo.register(frozen_model=_model(research_cutoff=cutoff), selected_at=cutoff)


def test_selection_requires_timezone_aware_timestamp(tmp_path):
    repo = RecommendationShadowPostSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="zona horaria"):
        repo.register(
            frozen_model=_model(research_cutoff=cutoff),
            selected_at=datetime(2025, 2, 1),
        )


def test_tampered_selection_record_is_rejected(tmp_path):
    repo = RecommendationShadowPostSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    record = repo.register(
        frozen_model=_model(research_cutoff=cutoff),
        selected_at=cutoff + timedelta(days=10),
    )
    record["selected_at"] = (cutoff + timedelta(days=5)).isoformat()

    with pytest.raises(ValueError, match="modificada"):
        repo.validate_record(record)
