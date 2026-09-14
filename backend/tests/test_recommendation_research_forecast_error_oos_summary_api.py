from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from fastapi.testclient import TestClient

from app.api import recommendation_research_forecast_evaluation as api_module
from app.main import app


client = TestClient(app)
ERROR_A = "a" * 64
ERROR_B = "b" * 64
SPEC_A = "c" * 64
SPEC_B = "d" * 64
SUMMARY = "e" * 64
COHORT = "f" * 64


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
            "artifact": SummaryService().build(
                summary_id="athena-v1-30d",
                as_of=datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
            ),
        }


class CohortRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_by_hash(self, *, cohort_hash: str) -> dict[str, Any]:
        self.calls.append(cohort_hash)
        if cohort_hash != COHORT:
            raise ValueError("cohort inexistente")
        return {"cohort_hash": COHORT, "artifact": {"cohortHash": COHORT, "observationCount": 2}}


class ProspectiveService:
    def get(self, *, cohort_id: str) -> dict[str, Any]:
        if cohort_id != "preselected":
            raise ValueError("No existe la cohorte preseleccionada.")
        return {"cohortHash": "1" * 64, "sealedAt": "2026-07-31T00:00:00+00:00"}


class BindingService:
    def bind(self, *, cohort, error_records):
        return {"membershipComplete": True, "selectedCount": 2}


def install_prospective_fakes(monkeypatch):
    monkeypatch.setattr(api_module, "prospective_cohort_service", ProspectiveService())
    monkeypatch.setattr(api_module, "prospective_error_binding_service", BindingService())


class GovernedService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "module": "research_forecast_error_oos_diagnostic",
            "longitudinalSufficiency": {
                "status": "policy_not_precommitted",
                "policyApproved": False,
                "productionSufficiencyClaimed": False,
            },
            "productionLearningEligible": False,
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
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


def test_governed_oos_endpoint_requires_cohort_and_evaluates_policy(monkeypatch) -> None:
    errors, specifications, _, _ = install_fakes(monkeypatch)
    install_prospective_fakes(monkeypatch)
    cohorts = CohortRepository()
    governed = GovernedService()
    monkeypatch.setattr(api_module, "oos_cohort_repository", cohorts)
    monkeypatch.setattr(api_module, "governed_oos_service", governed)

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-governed",
        json={**request_body(), "cohortHash": COHORT, "prospectiveCohortId": "preselected"},
    )

    assert response.status_code == 200
    assert cohorts.calls == [COHORT]
    assert errors.calls == [ERROR_A, ERROR_B]
    assert specifications.calls == [SPEC_A, SPEC_B]
    assert len(governed.calls) == 1
    assert governed.calls[0]["cohort_record"]["cohort_hash"] == COHORT
    data = response.json()["data"]
    assert data["governance"]["policyEvaluated"] is True
    assert data["governance"]["prospectiveCohortHash"] == "1" * 64
    assert data["governance"]["automaticTrading"] is False
    assert data["productionLearningEligible"] is False


def test_governed_oos_endpoint_fails_closed_for_unknown_cohort(monkeypatch) -> None:
    install_fakes(monkeypatch)
    cohorts = CohortRepository()
    monkeypatch.setattr(api_module, "oos_cohort_repository", cohorts)

    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-governed",
        json={**request_body(), "cohortHash": "9" * 64, "prospectiveCohortId": "preselected"},
    )

    assert response.status_code == 400
    assert cohorts.calls == ["9" * 64]


def test_governed_oos_requires_explicit_prospective_selection():
    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-governed",
        json={**request_body(), "cohortHash": COHORT},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("failure", ["missing", "partial", "denominator", "future"])
def test_governed_oos_cannot_evaluate_policy_without_complete_ex_ante_selection(monkeypatch, failure):
    install_fakes(monkeypatch)
    install_prospective_fakes(monkeypatch)
    monkeypatch.setattr(api_module, "oos_cohort_repository", CohortRepository())
    governed = GovernedService()
    monkeypatch.setattr(api_module, "governed_oos_service", governed)
    cohort_id = "unknown" if failure == "missing" else "preselected"
    if failure in {"partial", "denominator"}:
        monkeypatch.setattr(api_module.prospective_error_binding_service, "bind", lambda **kw: {
            "membershipComplete": failure != "partial", "selectedCount": 3,
        })
    if failure == "future":
        monkeypatch.setattr(api_module.prospective_cohort_service, "get", lambda **kw: {
            "cohortHash": "1" * 64, "sealedAt": "2026-09-02T00:00:00+00:00",
        })
    response = client.post(
        "/api/v1/recommendations/professional-research/forecast-error-oos-governed",
        json={**request_body(), "cohortHash": COHORT, "prospectiveCohortId": cohort_id},
    )
    assert response.status_code == 400
    assert governed.calls == []


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
    errors, specifications, service, summaries = install_fakes(monkeypatch)

    response = client.get(
        f"/api/v1/recommendations/professional-research/forecast-error-oos-summary/{SUMMARY}"
    )

    assert response.status_code == 200
    assert summaries.get_calls == [SUMMARY]
    assert errors.calls == [ERROR_A, ERROR_B]
    assert specifications.calls == [SPEC_A, SPEC_B]
    assert service.calls[0]["as_of"].isoformat() == request_body()["asOf"]
    assert summaries.appended == []  # Revalidation must not rewrite the snapshot.
    data = response.json()["data"]
    assert data["summaryHash"] == SUMMARY
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False


@pytest.mark.parametrize("repository_name", ["error_repository", "specification_repository"])
def test_oos_summary_read_rejects_missing_original_evidence(monkeypatch, repository_name):
    _, _, service, summaries = install_fakes(monkeypatch)

    class Missing:
        def get_by_hash(self, **kwargs):
            raise ValueError("evidencia original inexistente")

    monkeypatch.setattr(api_module, repository_name, Missing())
    response = client.get(f"{api_module.router.prefix}/forecast-error-oos-summary/{SUMMARY}")
    assert response.status_code == 404
    assert "original inexistente" in response.json()["detail"]
    assert service.calls == []
    assert summaries.appended == []


@pytest.mark.parametrize("prefix", ["urn:athena:macro-pit:", "urn:athena:market-pit:"])
def test_oos_summary_read_revalidates_persisted_inputs_before_rebuilding(monkeypatch, prefix):
    _, _, service, _ = install_fakes(monkeypatch)

    class Specifications:
        def get_by_hash(self, **kwargs):
            return {"artifact": {"inputEvidence": [{"sourceRef": prefix + "a" * 64}]}}

    class ChangedInputs:
        uses_persisted_macro_inputs = staticmethod(
            api_module.PersistedMacroForecastInputService.uses_persisted_macro_inputs
        )
        def verify_specification(self, artifact):
            raise ValueError("input original modificado")

    monkeypatch.setattr(api_module, "specification_repository", Specifications())
    monkeypatch.setattr(api_module, "persisted_macro_input_service", ChangedInputs())
    response = client.get(f"{api_module.router.prefix}/forecast-error-oos-summary/{SUMMARY}")
    assert response.status_code == 404
    assert "input original modificado" in response.json()["detail"]
    assert service.calls == []


def test_oos_summary_read_rejects_rebuilt_snapshot_mismatch(monkeypatch):
    _, _, service, _ = install_fakes(monkeypatch)
    original = service.build

    def changed(**kwargs):
        artifact = original(**kwargs)
        artifact["metrics"]["meanAbsoluteError"] = 0.5
        return artifact

    monkeypatch.setattr(service, "build", changed)
    response = client.get(f"{api_module.router.prefix}/forecast-error-oos-summary/{SUMMARY}")
    assert response.status_code == 404
    assert "evidencia persistida revalidada" in response.json()["detail"]


def test_oos_summary_read_surfaces_transient_storage_failure_without_snapshot_fallback(monkeypatch):
    install_fakes(monkeypatch)

    class Unavailable:
        def get_by_hash(self, **kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(api_module, "error_repository", Unavailable())
    response = client.get(f"{api_module.router.prefix}/forecast-error-oos-summary/{SUMMARY}")
    assert response.status_code == 500
    assert "storage unavailable" not in response.text


@pytest.mark.parametrize("change", [None, "late_seal", "future_error"])
def test_oos_summary_real_persistence_replays_temporal_evidence(monkeypatch, tmp_path, change):
    """Synthetic records test replay; they are not longitudinal production evidence."""
    from datetime import timedelta
    from app.database.athena_database import AthenaDatabase
    from app.repositories.recommendation_research_forecast_error_oos_summary_repository import (
        RecommendationResearchForecastErrorOosSummaryRepository,
    )
    from app.services.recommendation_research_forecast_error_oos_summary_service import (
        RecommendationResearchForecastErrorOosSummaryService,
    )
    from test_recommendation_research_forecast_error_oos_summary_service import AS_OF, dataset

    errors, specifications = dataset()
    service = RecommendationResearchForecastErrorOosSummaryService()
    artifact = service.build(
        summary_id="replay-regression", as_of=AS_OF,
        error_records=errors, specification_records=specifications,
    )
    repository = RecommendationResearchForecastErrorOosSummaryRepository(
        AthenaDatabase(tmp_path / "summary-replay.db")
    )
    repository.append(artifact=artifact)

    class Errors:
        def get_by_hash(self, *, error_hash):
            return next(record for record in errors if record["error_hash"] == error_hash)

    class Specifications:
        def get_by_hash(self, *, specification_hash):
            return next(record for record in specifications if record["specification_hash"] == specification_hash)

    monkeypatch.setattr(api_module, "error_repository", Errors())
    monkeypatch.setattr(api_module, "specification_repository", Specifications())
    monkeypatch.setattr(api_module, "oos_summary_service", service)
    monkeypatch.setattr(api_module, "oos_summary_repository", repository)
    if change == "late_seal":
        start = datetime.fromisoformat(specifications[0]["artifact"]["periodStart"])
        specifications[0]["created_at"] = (start + timedelta(microseconds=1)).isoformat()
    elif change == "future_error":
        errors[0]["created_at"] = (AS_OF + timedelta(microseconds=1)).isoformat()

    response = client.get(
        f"{api_module.router.prefix}/forecast-error-oos-summary/{artifact['summaryHash']}"
    )
    assert response.status_code == (200 if change is None else 404), response.text
    if change is None:
        assert response.json()["data"] == artifact
    # A failed replay does not mutate the append-only historical snapshot.
    assert repository.get_by_hash(summary_hash=artifact["summaryHash"])["artifact"] == artifact
