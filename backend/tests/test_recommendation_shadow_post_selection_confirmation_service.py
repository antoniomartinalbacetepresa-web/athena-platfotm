from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)
from app.services.recommendation_shadow_post_selection_confirmation_service import (
    RecommendationShadowPostSelectionConfirmationService,
)


class FakeDatasetService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "featureSchemaVersion": "shadow-evidence-v1",
            "rowCount": len(self.rows),
            "rows": self.rows,
        }


def _row(*, index: int, cutoff: datetime, evaluated: datetime, horizon: int = 30):
    signal = (index - 20) / 100.0
    return {
        "snapshotId": index + 1,
        "symbol": "TEST",
        "dataCutoffAt": cutoff.isoformat(),
        "outcomeEvaluatedAt": evaluated.isoformat(),
        "horizonDays": horizon,
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


def _frozen_and_service(
    rows: list[dict],
    *,
    research_cutoff: datetime,
    minimum_confirmation_rows: int = 5,
):
    dataset = FakeDatasetService(rows)
    frozen_service = RecommendationShadowIndependentHoldoutService(
        dataset_service=dataset,
        minimum_research_rows=30,
        minimum_holdout_rows=5,
    )
    frozen = frozen_service.freeze(
        research_cutoff=research_cutoff,
        horizon_days=30,
        ridge_lambda=1.0,
    )
    assert frozen["status"] == "shadow_model_frozen"
    service = RecommendationShadowPostSelectionConfirmationService(
        dataset_service=dataset,
        frozen_model_service=frozen_service,
        minimum_confirmation_rows=minimum_confirmation_rows,
    )
    return frozen, service


def test_confirmation_excludes_research_and_preselection_holdout_evidence():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    confirmation_start = start + timedelta(days=100)
    as_of = start + timedelta(days=150)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    inspected_holdout = [
        _row(
            index=50 + i,
            cutoff=research_cutoff + timedelta(days=i + 1),
            evaluated=research_cutoff + timedelta(days=i + 2),
        )
        for i in range(10)
    ]
    confirmation = [
        _row(
            index=80 + i,
            cutoff=confirmation_start + timedelta(days=i + 1),
            evaluated=confirmation_start + timedelta(days=i + 2),
        )
        for i in range(6)
    ]
    frozen, service = _frozen_and_service(
        research + inspected_holdout + confirmation,
        research_cutoff=research_cutoff,
    )

    result = service.evaluate(
        frozen_model=frozen,
        confirmation_start=confirmation_start,
        as_of=as_of,
    )

    assert result["status"] == "shadow_post_selection_confirmation_evaluated"
    assert result["confirmationRowCount"] == 6
    assert result["excludedBeforeOrAtConfirmationStartCount"] == 50
    assert result["postSelectionConfirmationEvidenceReady"] is True
    assert result["productionEligible"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["policy"]["priorHoldoutSelectionEvidenceReusable"] is False
    assert result["policy"]["refit"] is False
    assert result["policy"]["thresholdCalibration"] is False


def test_confirmation_excludes_outcomes_not_known_at_as_of():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    confirmation_start = start + timedelta(days=100)
    as_of = start + timedelta(days=130)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    mature = [
        _row(
            index=80 + i,
            cutoff=confirmation_start + timedelta(days=i + 1),
            evaluated=confirmation_start + timedelta(days=i + 2),
        )
        for i in range(5)
    ]
    future = _row(
        index=99,
        cutoff=confirmation_start + timedelta(days=10),
        evaluated=as_of + timedelta(days=1),
    )
    frozen, service = _frozen_and_service(
        research + mature + [future],
        research_cutoff=research_cutoff,
    )

    result = service.evaluate(
        frozen_model=frozen,
        confirmation_start=confirmation_start,
        as_of=as_of,
    )

    assert result["confirmationRowCount"] == 5
    assert result["excludedNotMatureCount"] == 1


def test_confirmation_blocks_when_fresh_sample_is_too_small():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    confirmation_start = start + timedelta(days=100)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    confirmation = [
        _row(
            index=80 + i,
            cutoff=confirmation_start + timedelta(days=i + 1),
            evaluated=confirmation_start + timedelta(days=i + 2),
        )
        for i in range(2)
    ]
    frozen, service = _frozen_and_service(
        research + confirmation,
        research_cutoff=research_cutoff,
        minimum_confirmation_rows=5,
    )

    result = service.evaluate(
        frozen_model=frozen,
        confirmation_start=confirmation_start,
        as_of=confirmation_start + timedelta(days=30),
    )

    assert result["status"] == "insufficient_post_selection_confirmation_data"
    assert result["confirmationRowCount"] == 2
    assert result["postSelectionConfirmationEvidenceReady"] is False
    assert result["productionEligible"] is False


def test_confirmation_start_must_be_strictly_after_research_cutoff():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    frozen, service = _frozen_and_service(research, research_cutoff=research_cutoff)

    with pytest.raises(ValueError, match="estrictamente posterior"):
        service.evaluate(
            frozen_model=frozen,
            confirmation_start=research_cutoff,
            as_of=research_cutoff + timedelta(days=10),
        )


def test_confirmation_boundaries_must_be_timezone_aware():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research_cutoff = start + timedelta(days=60)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    frozen, service = _frozen_and_service(research, research_cutoff=research_cutoff)

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            frozen_model=frozen,
            confirmation_start=datetime(2025, 4, 1),
            as_of=start + timedelta(days=150),
        )
