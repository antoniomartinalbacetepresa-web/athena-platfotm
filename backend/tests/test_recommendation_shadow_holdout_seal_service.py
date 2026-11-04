from __future__ import annotations

from datetime import datetime, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_holdout_seal_repository import (
    RecommendationShadowHoldoutSealRepository,
)
from app.services.recommendation_shadow_holdout_seal_service import (
    RecommendationShadowHoldoutSealService,
)


UTC = timezone.utc
GATE = "a" * 64
CUTOFF = "2026-01-01T00:00:00+00:00"


class FakePipeline:
    def __init__(self, *, evaluated: int, eligible: bool = False) -> None:
        self.evaluated = evaluated
        self.eligible = eligible
        self.calls = 0

    def evaluate_latest_cohort(self, **kwargs):
        self.calls += 1
        return {
            "status": "shadow_holdout_pipeline_evaluated",
            "researchGateFingerprint": GATE,
            "researchCutoff": CUTOFF,
            "holdoutGate": {
                "status": "gate",
                "evaluatedHorizonCount": self.evaluated,
                "actionThresholdCalibrationResearchEligible": self.eligible,
                "thresholds": {"minimumEvaluatedHorizons": 3},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


def _repo(tmp_path):
    return RecommendationShadowHoldoutSealRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def test_insufficient_mature_horizons_are_not_sealed(tmp_path):
    repository = _repo(tmp_path)
    service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(evaluated=2), repository=repository
    )
    result = service.evaluate_and_seal(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 30, 90)
    )
    assert result["holdoutSealed"] is False
    assert result["sealReason"] == "insufficient_mature_horizons_to_seal"
    assert repository.get(
        research_gate_fingerprint=GATE, research_cutoff=CUTOFF
    ) is None


def test_first_sufficient_result_is_sealed_even_when_gate_fails(tmp_path):
    repository = _repo(tmp_path)
    service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(evaluated=3, eligible=False), repository=repository
    )
    result = service.evaluate_and_seal(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 30, 90)
    )
    assert result["holdoutSealed"] is True
    assert result["reusedExistingSeal"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["productionEligible"] is False


def test_later_favourable_result_cannot_replace_first_failed_seal(tmp_path):
    repository = _repo(tmp_path)
    failing = FakePipeline(evaluated=3, eligible=False)
    first_service = RecommendationShadowHoldoutSealService(
        pipeline_service=failing, repository=repository
    )
    first = first_service.evaluate_and_seal(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 30, 90)
    )

    favourable = FakePipeline(evaluated=5, eligible=True)
    second_service = RecommendationShadowHoldoutSealService(
        pipeline_service=favourable, repository=repository
    )
    second = second_service.evaluate_and_seal(
        as_of=datetime(2027, 9, 1, tzinfo=UTC), horizons=(7, 30, 90, 180, 365)
    )

    assert first["pipelineFingerprint"] == second["pipelineFingerprint"]
    assert second["reusedExistingSeal"] is True
    assert second["actionThresholdCalibrationResearchEligible"] is False


def test_passing_first_result_is_still_research_only(tmp_path):
    repository = _repo(tmp_path)
    service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(evaluated=5, eligible=True), repository=repository
    )
    result = service.evaluate_and_seal(
        as_of=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert result["actionThresholdCalibrationResearchEligible"] is True
    assert result["policy"]["thresholdsCanBeFitOnThisHoldout"] is False
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False


def test_repository_keeps_first_pipeline_immutable(tmp_path):
    repository = _repo(tmp_path)
    pipeline = FakePipeline(evaluated=3, eligible=False).evaluate_latest_cohort()
    first = repository.seal(
        pipeline=pipeline, sealed_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    changed = FakePipeline(evaluated=5, eligible=True).evaluate_latest_cohort()
    second = repository.seal(
        pipeline=changed, sealed_at=datetime(2027, 9, 1, tzinfo=UTC)
    )
    assert first["pipeline_fingerprint"] == second["pipeline_fingerprint"]
    assert second["pipeline"]["holdoutGate"]["actionThresholdCalibrationResearchEligible"] is False
