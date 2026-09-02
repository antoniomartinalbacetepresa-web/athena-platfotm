from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_post_selection_repository import (
    RecommendationShadowPostSelectionRepository,
)
from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)
from app.services.recommendation_shadow_post_selection_confirmation_service import (
    RecommendationShadowPostSelectionConfirmationService,
)
from app.services.recommendation_shadow_post_selection_pipeline_service import (
    RecommendationShadowPostSelectionPipelineService,
)


class FakeDatasetService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def build(self, **kwargs):
        return {
            "featureSchemaVersion": "shadow-evidence-v1",
            "rowCount": len(self.rows),
            "rows": self.rows,
        }


def _row(*, index: int, cutoff: datetime, evaluated: datetime):
    signal = (index - 20) / 100.0
    return {
        "snapshotId": index + 1,
        "symbol": "TEST",
        "dataCutoffAt": cutoff.isoformat(),
        "outcomeEvaluatedAt": evaluated.isoformat(),
        "horizonDays": 30,
        "features": {
            "technicalScore": float(index),
            "riskScore": float(index % 5),
        },
        "target": {
            "excessReturn": signal,
            "realizedReturn": signal,
            "benchmarkReturn": 0.0,
        },
    }


def _pipeline(tmp_path, rows):
    dataset = FakeDatasetService(rows)
    frozen = RecommendationShadowIndependentHoldoutService(
        dataset_service=dataset,
        minimum_research_rows=30,
        minimum_holdout_rows=5,
    )
    confirmation = RecommendationShadowPostSelectionConfirmationService(
        dataset_service=dataset,
        frozen_model_service=frozen,
        minimum_confirmation_rows=5,
    )
    return RecommendationShadowPostSelectionPipelineService(
        repository=RecommendationShadowPostSelectionRepository(
            AthenaDatabase(tmp_path / "athena.db")
        ),
        frozen_model_service=frozen,
        confirmation_service=confirmation,
    ), frozen


def test_registered_boundary_is_used_for_confirmation(tmp_path):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    selected_at = start + timedelta(days=100)
    as_of = start + timedelta(days=150)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    inspected = [
        _row(
            index=50 + i,
            cutoff=research_cutoff + timedelta(days=i + 1),
            evaluated=research_cutoff + timedelta(days=i + 2),
        )
        for i in range(10)
    ]
    fresh = [
        _row(
            index=80 + i,
            cutoff=selected_at + timedelta(days=i + 1),
            evaluated=selected_at + timedelta(days=i + 2),
        )
        for i in range(6)
    ]
    pipeline, frozen_service = _pipeline(tmp_path, research + inspected + fresh)
    model = frozen_service.freeze(
        research_cutoff=research_cutoff,
        horizon_days=30,
        ridge_lambda=1.0,
    )

    registered = pipeline.register_selection(frozen_model=model, selected_at=selected_at)
    result = pipeline.evaluate_registered_selection(
        model_fingerprint=model["fingerprint"],
        as_of=as_of,
    )

    assert registered["confirmationStart"] == selected_at.isoformat()
    assert result["confirmationStart"] == selected_at.isoformat()
    assert result["confirmationRowCount"] == 6
    assert result["selectionBoundaryPersisted"] is True
    assert result["productionEligible"] is False
    assert result["advisoryStatus"] == "no_advice"


def test_reregister_cannot_move_confirmation_boundary_after_evidence(tmp_path):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    first_selection = start + timedelta(days=100)
    later_selection = start + timedelta(days=130)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    pipeline, frozen_service = _pipeline(tmp_path, research)
    model = frozen_service.freeze(
        research_cutoff=research_cutoff,
        horizon_days=30,
        ridge_lambda=1.0,
    )

    first = pipeline.register_selection(frozen_model=model, selected_at=first_selection)
    second = pipeline.register_selection(frozen_model=model, selected_at=later_selection)

    assert first["selectionFingerprint"] == second["selectionFingerprint"]
    assert second["confirmationStart"] == first_selection.isoformat()


def test_unregistered_model_cannot_be_confirmed(tmp_path):
    pipeline, _ = _pipeline(tmp_path, [])

    result = pipeline.evaluate_registered_selection(
        model_fingerprint="b" * 64,
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "shadow_post_selection_not_registered"
    assert result["postSelectionConfirmationEvidenceReady"] is False
    assert result["productionEligible"] is False
