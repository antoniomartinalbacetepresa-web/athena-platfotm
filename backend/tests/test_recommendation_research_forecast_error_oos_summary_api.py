from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from app.api import recommendation_research_forecast_evaluation as api_module
from app.main import app


client = TestClient(app)
ERROR_A = "a" * 64
ERROR_B = "b" * 64
SPEC_A = "c" * 64
SPEC_B = "d" * 64
SUMMARY = "e" * 64


class ErrorRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_by_hash(self, *, error_hash: str) -> dict[str, Any]:
        self.calls.append(error_hash)
        mapping = {
            ERROR_A: {
                "error_hash": ERROR_A,
                "artifact": {"specificationHash": SPEC_A},
                "created_at": "2026-08-31T00:00:00+00:00",
            },
            ERROR_B: {
                "error_hash": ERROR_B,
                "artifact": {"specificationHash": SPEC_B},
                "created_at": "2026-08-31T00:00:00+00:00",
            },
        }
        if error_hash not in mapping:
            raise ValueError("forecast error inexistente")
        return mapping[error_hash]


class SpecificationRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_by_hash(self, *, specification_hash: str) -> dict[str, Any]:
        self.calls.append(specification_hash)
        if specification_hash not in {SPEC_A, SPEC_B}:
            raise ValueError("specification inexistente")
        return {
            "specification_hash": specification_hash,
            "artifact": {"specificationHash": specification_hash},
            "created_at": "2026-08-01T00:00:00+00:00",
        }


class SummaryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "module": "research_forecast_error_oos_summary",
            "artifactVersion": "research-forecast-error-oos-summary-v1",
            "summaryId": kwargs["summary_id"],
            "summaryHash": SUMMARY,
            "asOf": kwargs["as_of"].isoformat(),
            "method": "athena-v1",
            "horizonSeconds": 2592000,
            "observationCount": 2,
            "distinctInstrumentCount": 2,
            "maximumObservationsPerInstrument": 1,
            "overlappingPeriodPairCount": 0,
            "metrics": {
                "meanSignedError": 0.0,
                "meanAbsoluteError": 0.02,
                "rootMeanSquaredError": 0.02,
                "medianAbsoluteError": 0.02,
            },
            "errorHashes": [ERROR_A, ERROR_B],
            "rows": [],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "learningResearchDatasetReady": True,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "statisticalIndependence": "not_claimed",
                "skillClaim": "forbidden_descriptive_errors_do_not_establish_skill",
                "thresholdCalibration": "not_calibrated",
                "recommendationReadiness": "not_established",
            },
        }


class SummaryRepository:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.appended.append(artifact)
        return {"summary_hash": SUMMARY, "artifact": artifact}

    def get_by_hash(self, *, summary_hash: str) -> dict[str, Any]:
        self.get_calls.append(summary_hash)
        if summary_hash != SUMMARY:
            raise ValueError("summary inexistente")
        return {
            "summary_hash": SUMMARY,
            "artifact": {
                "module": "research_forecast_error_oos_summary",
                "summaryHash": SUMMARY,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
            },
        }


def request_body() -> dict[str, object]:
    return {
        "summaryId": "athena-v1-30d",
        "asOf": "2026-09-01T00:00:00+00:00",
        "errorHashes": [ERROR_A, ERROR_B],
    }


def install_fakes(monkeypatch):
    errors = ErrorRepository()
    specifications = SpecificationRepository()
    service = SummaryService()
    summaries = SummaryRepository()
    monkeypatch.setattr(api_module, "error_repository", errors)
    monkeypatch.setattr(api_module, "specification_repository", specifications)
    monkeypatch.setattr(api_module, "oos_summary_service", service)
    monkeypatch.setattr(api_module, "oos_summary_repository", summaries)
    return errors, specifications, service, summaries


def test_oos_summary_api_uses_only_persisted_error_and_specification_records(monkeypatch) -> None:
    errors, specifications, service, summaries = install_fakes(monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-summary",
        json=request_body(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert errors.calls == [ERROR_A, ERROR_B]
    assert specifications.calls == [SPEC_A, SPEC_B]
    assert len(service.calls) == 1
    assert len(service.calls[0]["error_records"]) == 2
    assert len(service.calls[0]["specification_records"]) == 2
    assert summaries.appended[0]["summaryHash"] == SUMMARY
    assert data["summaryHash"] == SUMMARY
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["recommendationCandidateReady"] is False
    assert data["productionLearningEligible"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["thresholdCalibration"] == "not_calibrated"
    assert data["persistence"]["semanticIntegrityVerified"] is True


def test_oos_summary_api_rejects_duplicate_error_hashes_before_lookup(monkeypatch) -> None:
    errors, specifications, service, summaries = install_fakes(monkeypatch)
    body = request_body()
    body["errorHashes"] = [ERROR_A, ERROR_A]

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-summary",
        json=body,
    )

    assert response.status_code == 400
    assert "duplicados" in response.json()["detail"]
    assert errors.calls == []
    assert specifications.calls == []
    assert service.calls == []
    assert summaries.appended == []


def test_oos_summary_api_rejects_naive_as_of_before_repository_access(monkeypatch) -> None:
    errors, specifications, service, summaries = install_fakes(monkeypatch)
    body = request_body()
    body["asOf"] = "2026-09-01T00:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-summary",
        json=body,
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert errors.calls == []
    assert specifications.calls == []
    assert service.calls == []
    assert summaries.appended == []


def test_oos_summary_api_fails_closed_when_persisted_error_is_missing(monkeypatch) -> None:
    errors, specifications, service, summaries = install_fakes(monkeypatch)
    body = request_body()
    body["errorHashes"] = ["9" * 64]

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-summary",
        json=body,
    )

    assert response.status_code == 400
    assert "inexistente" in response.json()["detail"]
    assert specifications.calls == []
    assert service.calls == []
    assert summaries.appended == []


def test_oos_summary_get_endpoint_returns_only_persisted_artifact(monkeypatch) -> None:
    _, _, _, summaries = install_fakes(monkeypatch)

    response = client.get(
        f"/api/v1/recommendations/professional-research/forecast-error-oos-summary/{SUMMARY}"
    )

    assert response.status_code == 200
    assert summaries.get_calls == [SUMMARY]
    data = response.json()["data"]
    assert data["summaryHash"] == SUMMARY
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
