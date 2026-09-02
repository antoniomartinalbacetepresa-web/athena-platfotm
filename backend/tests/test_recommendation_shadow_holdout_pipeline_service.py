from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_holdout_pipeline_service import (
    RecommendationShadowHoldoutPipelineService,
)


UTC = timezone.utc


def _bundle(*, horizon: int, cutoff: str, gate: str, suffix: str) -> dict:
    return {
        "status": "shadow_research_gated_model_frozen",
        "productionEligible": False,
        "advisoryStatus": "no_advice",
        "horizonDays": horizon,
        "researchCutoff": cutoff,
        "researchGateFingerprint": gate,
        "bundleFingerprint": (suffix * 64)[:64],
        "frozenModel": {"fingerprint": f"model-{suffix}-{horizon}"},
    }


class FakeRepository:
    def __init__(self, records_by_horizon: dict[int, list[dict]]) -> None:
        self.records_by_horizon = records_by_horizon

    def list_for_horizon(self, *, horizon_days: int) -> list[dict]:
        return self.records_by_horizon.get(horizon_days, [])


class FakeFreezeValidator:
    def validate_bundle(self, bundle: dict) -> dict:
        return bundle


class FakeHoldout:
    def evaluate(self, *, frozen_model: dict, as_of: datetime) -> dict:
        horizon = int(frozen_model["fingerprint"].rsplit("-", 1)[1])
        return {
            "status": "shadow_independent_holdout_evaluated",
            "modelFingerprint": frozen_model["fingerprint"],
            "horizonDays": horizon,
            "holdoutRowCount": 25,
            "relativeMseImprovement": 0.1,
            "beatsZeroBaselineOnMse": True,
            "metrics": {"signAccuracy": 0.6},
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


class FakeGate:
    def evaluate(self, *, holdouts: dict) -> dict:
        evaluated = sum(
            evidence.get("status") == "shadow_independent_holdout_evaluated"
            for evidence in holdouts.values()
        )
        return {
            "status": "fake_holdout_gate",
            "actionThresholdCalibrationResearchEligible": evaluated >= 2,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


def _service(records: dict[int, list[dict]]) -> RecommendationShadowHoldoutPipelineService:
    return RecommendationShadowHoldoutPipelineService(
        repository=FakeRepository(records),
        gated_freeze_service=FakeFreezeValidator(),
        holdout_service=FakeHoldout(),
        holdout_gate_service=FakeGate(),
    )


def test_evaluates_only_latest_coherent_research_cohort() -> None:
    old_gate = "a" * 64
    new_gate = "b" * 64
    old_cutoff = "2026-01-01T00:00:00+00:00"
    new_cutoff = "2026-06-01T00:00:00+00:00"
    records = {
        7: [
            {"bundle": _bundle(horizon=7, cutoff=old_cutoff, gate=old_gate, suffix="1")},
            {"bundle": _bundle(horizon=7, cutoff=new_cutoff, gate=new_gate, suffix="2")},
        ],
        30: [
            {"bundle": _bundle(horizon=30, cutoff=old_cutoff, gate=old_gate, suffix="3")},
            {"bundle": _bundle(horizon=30, cutoff=new_cutoff, gate=new_gate, suffix="4")},
        ],
    }
    result = _service(records).evaluate_latest_cohort(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 30)
    )
    assert result["researchGateFingerprint"] == new_gate
    assert result["researchCutoff"] == new_cutoff
    assert result["persistedCandidateHorizons"] == [7, 30]
    assert result["actionThresholdCalibrationResearchEligible"] is True
    assert result["productionEligible"] is False


def test_missing_horizon_stays_explicit_and_cannot_be_silently_reused_from_other_cohort() -> None:
    gate_a = "a" * 64
    gate_b = "b" * 64
    cutoff_a = "2026-04-01T00:00:00+00:00"
    cutoff_b = "2026-06-01T00:00:00+00:00"
    records = {
        7: [{"bundle": _bundle(horizon=7, cutoff=cutoff_b, gate=gate_b, suffix="5")}],
        30: [{"bundle": _bundle(horizon=30, cutoff=cutoff_a, gate=gate_a, suffix="6")}],
    }
    result = _service(records).evaluate_latest_cohort(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 30)
    )
    assert result["researchGateFingerprint"] == gate_b
    assert result["persistedCandidateHorizons"] == [7]
    assert result["holdouts"][30]["status"] == "frozen_candidate_missing_for_cohort"
    assert result["actionThresholdCalibrationResearchEligible"] is False


def test_future_or_same_cutoff_candidate_is_not_holdout_eligible() -> None:
    gate = "c" * 64
    cutoff = "2026-09-01T00:00:00+00:00"
    records = {7: [{"bundle": _bundle(horizon=7, cutoff=cutoff, gate=gate, suffix="7")}]}
    result = _service(records).evaluate_latest_cohort(
        as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7,)
    )
    assert result["status"] == "shadow_holdout_no_eligible_frozen_cohort"
    assert result["productionEligible"] is False


def test_duplicate_candidates_inside_same_cohort_are_rejected() -> None:
    gate = "d" * 64
    cutoff = "2026-05-01T00:00:00+00:00"
    records = {
        7: [
            {"bundle": _bundle(horizon=7, cutoff=cutoff, gate=gate, suffix="8")},
            {"bundle": _bundle(horizon=7, cutoff=cutoff, gate=gate, suffix="9")},
        ]
    }
    with pytest.raises(ValueError, match="más de un candidato"):
        _service(records).evaluate_latest_cohort(
            as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7,)
        )


def test_naive_as_of_and_duplicate_horizons_are_rejected() -> None:
    service = _service({})
    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate_latest_cohort(as_of=datetime(2026, 9, 1), horizons=(7,))
    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate_latest_cohort(
            as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7, 7)
        )


def test_production_eligible_bundle_is_rejected_even_if_validator_returns_it() -> None:
    gate = "e" * 64
    cutoff = "2026-05-01T00:00:00+00:00"
    bad = _bundle(horizon=7, cutoff=cutoff, gate=gate, suffix="a")
    bad["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible=False"):
        _service({7: [{"bundle": bad}]}).evaluate_latest_cohort(
            as_of=datetime(2026, 9, 1, tzinfo=UTC), horizons=(7,)
        )
