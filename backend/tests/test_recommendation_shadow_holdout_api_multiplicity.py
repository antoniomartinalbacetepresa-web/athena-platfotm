from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import recommendation_research
from app.main import app


class FakeHoldoutSealService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate_and_seal(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def _payload(
    *,
    raw=True,
    final=False,
    count=2,
    controlled=False,
    correction="not_yet_implemented",
    lineage_complete=True,
):
    return {
        "status": "shadow_independent_holdout_sealed",
        "holdoutSealed": True,
        "rawHoldoutGateEligible": raw,
        "actionThresholdCalibrationResearchEligible": final,
        "experimentMultiplicity": {
            "experimentFamily": "shadow-ridge-excess-return-v1",
            "distinctHoldoutExperimentCount": count,
            "multiplicityPresent": count > 1,
            "multiplicityControlled": controlled,
            "correctionMethod": correction,
            "firstExposureLineageComplete": lineage_complete,
            "experiments": [],
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "policy": {
            "automaticProductionPromotion": False,
            "actions": "not_assigned",
        },
    }


def test_api_exposes_raw_pass_but_keeps_uncorrected_multi_cohort_result_blocked(monkeypatch):
    fake = FakeHoldoutSealService(_payload())
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness",
        params={"as_of": "2026-09-02T07:00:00+00:00"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rawHoldoutGateEligible"] is True
    assert data["actionThresholdCalibrationResearchEligible"] is False
    assert data["experimentMultiplicity"]["distinctHoldoutExperimentCount"] == 2
    assert data["productionEligible"] is False


def test_api_fails_closed_if_uncorrected_multiplicity_is_promoted(monkeypatch):
    fake = FakeHoldoutSealService(_payload(final=True))
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness"
    )

    assert response.status_code == 500
    assert "multiplicidad" in response.json()["detail"].lower()


def test_api_fails_closed_if_final_eligibility_is_not_backed_by_raw_holdout(monkeypatch):
    fake = FakeHoldoutSealService(
        _payload(
            raw=False,
            final=True,
            count=1,
            controlled=True,
            correction="not_required",
        )
    )
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness"
    )

    assert response.status_code == 500
    assert "elegibilidad final" in response.json()["detail"].lower()


def test_api_fails_closed_if_first_exposure_lineage_is_incomplete(monkeypatch):
    fake = FakeHoldoutSealService(
        _payload(
            raw=True,
            final=True,
            count=1,
            controlled=True,
            correction="not_required",
            lineage_complete=False,
        )
    )
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness"
    )

    assert response.status_code == 500
    assert "linaje" in response.json()["detail"].lower()


def test_api_accepts_single_controlled_experiment_when_raw_gate_passes(monkeypatch):
    fake = FakeHoldoutSealService(
        _payload(
            raw=True,
            final=True,
            count=1,
            controlled=True,
            correction="not_required",
            lineage_complete=True,
        )
    )
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness"
    )

    assert response.status_code == 200
    assert response.json()["data"]["actionThresholdCalibrationResearchEligible"] is True
