from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import recommendation_fundamental_factor_evidence as api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"


class Service:
    def __init__(self, artifact):
        self.artifact = artifact
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.artifact)

    def validate_artifact(self, artifact):
        return artifact


class Repository:
    def __init__(self):
        self.calls = []

    def append(self, *, artifact):
        self.calls.append(artifact)
        return {"artifact": artifact}


def quality_artifact(**overrides):
    payload = {
        "module": "pit_quality_factor_exposure",
        "factorExposureKey": "a" * 64,
        "instrumentId": 1,
        "asOf": AS_OF,
        "availableAt": AS_OF,
        "operatingMargin": 0.2,
        "operatingMarginEvidenceKey": "b" * 64,
        "issuerId": 10,
        "cik": "0000000001",
        "universeCount": 20,
        "universeFingerprint": "c" * 64,
        "factors": {"quality": 0.25},
        "provenance": {},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "thresholds": "not_calibrated",
            "qualityDefinition": "single_metric_operating_margin_not_composite_quality",
            "sectorNeutralization": "not_performed_or_claimed",
        },
    }
    payload.update(overrides)
    return payload


def margin_artifact(*, status="resolved", **overrides):
    payload = {
        "module": "operating_margin_pit_evidence",
        "status": status,
        "evidenceKey": "d" * 64 if status == "resolved" else None,
        "instrumentId": 1,
        "asOf": AS_OF,
        "availableAt": AS_OF if status == "resolved" else None,
        "operatingMargin": 0.2 if status == "resolved" else None,
        "factorReady": False,
        "factorExposure": None,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "qualityDefinition": "single_metric_operating_margin_not_composite_quality",
            "sectorNeutralization": "not_performed_or_claimed",
        },
    }
    payload.update(overrides)
    return payload


def test_quality_endpoint_persists_research_only_artifact(monkeypatch) -> None:
    service = Service(quality_artifact())
    repository = Repository()
    monkeypatch.setattr(api, "_quality_service", service)
    monkeypatch.setattr(api, "_quality_repository", repository)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/quality",
        json={"instrumentId": 1, "asOf": AS_OF},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["factors"]["quality"] == 0.25
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert len(repository.calls) == 1


def test_quality_endpoint_fails_closed_on_unsafe_or_nonfinite_output(monkeypatch) -> None:
    repository = Repository()
    monkeypatch.setattr(api, "_quality_repository", repository)
    for artifact in (
        quality_artifact(productionEligible=True),
        quality_artifact(isWeightingReady=True),
        quality_artifact(factors={"quality": float("nan")}),
        quality_artifact(factors={"quality": 2.0}),
        quality_artifact(policy={"automaticTrading": True, "automaticProductionPromotion": False, "thresholds": "not_calibrated", "qualityDefinition": "single_metric_operating_margin_not_composite_quality", "sectorNeutralization": "not_performed_or_claimed"}),
    ):
        monkeypatch.setattr(api, "_quality_service", Service(artifact))
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-exposure/quality",
            json={"instrumentId": 1, "asOf": AS_OF},
        )
        assert response.status_code == 500


def test_operating_margin_missing_is_returned_unknown_and_not_persisted(monkeypatch) -> None:
    service = Service(margin_artifact(status="missing"))
    repository = Repository()
    monkeypatch.setattr(api, "_margin_service", service)
    monkeypatch.setattr(api, "_margin_repository", repository)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/operating-margin",
        json={"instrumentId": 1, "asOf": AS_OF},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "missing"
    assert response.json()["data"]["operatingMargin"] is None
    assert repository.calls == []


def test_quality_and_margin_reject_naive_asof_before_service(monkeypatch) -> None:
    quality = Service(quality_artifact())
    margin = Service(margin_artifact())
    monkeypatch.setattr(api, "_quality_service", quality)
    monkeypatch.setattr(api, "_margin_service", margin)
    for path in ("factor-exposure/quality", "factor-evidence/operating-margin"):
        response = client.post(
            f"/api/v1/recommendations/professional-research/{path}",
            json={"instrumentId": 1, "asOf": "2026-01-01T00:00:00"},
        )
        assert response.status_code == 400
    assert quality.calls == []
    assert margin.calls == []
