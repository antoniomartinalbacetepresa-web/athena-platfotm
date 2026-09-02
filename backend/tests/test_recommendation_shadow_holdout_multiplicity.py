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


class FakePipeline:
    def __init__(self, *, gate: str, cutoff: str, eligible: bool = True, evaluated: int = 3) -> None:
        self.gate = gate
        self.cutoff = cutoff
        self.eligible = eligible
        self.evaluated = evaluated

    def evaluate_latest_cohort(self, **kwargs):
        return {
            "status": "shadow_holdout_pipeline_evaluated",
            "researchGateFingerprint": self.gate,
            "researchCutoff": self.cutoff,
            "holdoutGate": {
                "status": "shadow_holdout_gate",
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


def test_repeated_same_cohort_is_one_holdout_experiment(tmp_path):
    repository = _repo(tmp_path)
    service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(
            gate="a" * 64,
            cutoff="2026-01-01T00:00:00+00:00",
            eligible=True,
        ),
        repository=repository,
    )

    first = service.evaluate_and_seal(as_of=datetime(2026, 9, 1, tzinfo=UTC))
    second = service.evaluate_and_seal(as_of=datetime(2026, 10, 1, tzinfo=UTC))

    assert first["actionThresholdCalibrationResearchEligible"] is True
    assert second["reusedExistingSeal"] is True
    assert second["experimentMultiplicity"]["distinctHoldoutExperimentCount"] == 1
    assert second["experimentMultiplicity"]["multiplicityControlled"] is True


def test_second_distinct_cohort_revokes_uncorrected_promotion(tmp_path):
    repository = _repo(tmp_path)
    first_service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(
            gate="a" * 64,
            cutoff="2026-01-01T00:00:00+00:00",
            eligible=True,
        ),
        repository=repository,
    )
    second_service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(
            gate="b" * 64,
            cutoff="2026-02-01T00:00:00+00:00",
            eligible=True,
        ),
        repository=repository,
    )

    first_service.evaluate_and_seal(as_of=datetime(2026, 9, 1, tzinfo=UTC))
    second = second_service.evaluate_and_seal(as_of=datetime(2026, 10, 1, tzinfo=UTC))
    first_rechecked = first_service.evaluate_and_seal(
        as_of=datetime(2026, 11, 1, tzinfo=UTC)
    )

    assert second["rawHoldoutGateEligible"] is True
    assert second["actionThresholdCalibrationResearchEligible"] is False
    assert second["experimentMultiplicity"]["distinctHoldoutExperimentCount"] == 2
    assert second["experimentMultiplicity"]["multiplicityPresent"] is True
    assert second["experimentMultiplicity"]["multiplicityControlled"] is False
    assert second["experimentMultiplicity"]["correctionMethod"] == "not_yet_implemented"
    assert first_rechecked["rawHoldoutGateEligible"] is True
    assert first_rechecked["actionThresholdCalibrationResearchEligible"] is False


def test_insufficient_mature_holdout_still_counts_as_exposure(tmp_path):
    repository = _repo(tmp_path)
    service = RecommendationShadowHoldoutSealService(
        pipeline_service=FakePipeline(
            gate="c" * 64,
            cutoff="2026-03-01T00:00:00+00:00",
            eligible=False,
            evaluated=1,
        ),
        repository=repository,
    )

    result = service.evaluate_and_seal(as_of=datetime(2026, 9, 1, tzinfo=UTC))

    assert result["holdoutSealed"] is False
    assert result["sealReason"] == "insufficient_mature_horizons_to_seal"
    assert result["experimentMultiplicity"]["distinctHoldoutExperimentCount"] == 1


def test_existing_seals_are_backfilled_into_attempt_lineage(tmp_path):
    repository = _repo(tmp_path)
    pipeline = FakePipeline(
        gate="d" * 64,
        cutoff="2026-04-01T00:00:00+00:00",
        eligible=False,
    ).evaluate_latest_cohort()
    repository.seal(
        pipeline=pipeline,
        sealed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    summary = repository.multiplicity_summary()

    assert summary["distinctHoldoutExperimentCount"] == 1
    assert summary["experiments"][0]["research_gate_fingerprint"] == "d" * 64
