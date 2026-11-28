"""Synthetic regressions, not production PIT or forecast evidence."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.api import recommendation_research_forecast_evaluation as api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_macro_pit_observation_repository import RecommendationMacroPitObservationRepository
from app.repositories.recommendation_research_evaluation_specification_repository import RecommendationResearchEvaluationSpecificationRepository
from app.services.recommendation_macro_pit_observation_service import RecommendationMacroPitObservationService
from app.services.persisted_macro_forecast_input_service import PersistedMacroForecastInputService
from test_recommendation_research_forecast_evaluation import _cycle_record, CYCLE_HASH


@pytest.fixture
def context(tmp_path):
    database = AthenaDatabase(tmp_path / "inputs.db")
    repository = RecommendationMacroPitObservationRepository(database)
    now = datetime.now(timezone.utc)
    artifact = RecommendationMacroPitObservationService().build_artifact(
        series_id="GDP", value=100, observed_at=now - timedelta(days=60),
        available_at=now - timedelta(days=30), source_provider="fred_alfred",
        source_ref="urn:test:gdp-vintage", unit="index",
    )
    record = repository.append(artifact=artifact)
    persisted_at = datetime.fromisoformat(record["created_at"])
    cutoff = persisted_at + timedelta(seconds=1)
    forecast_at = cutoff + timedelta(seconds=1)
    cycle = _cycle_record()
    cycle["package"]["cycle"]["asOf"] = cutoff.isoformat()
    return database, repository, record, cutoff, forecast_at, cycle


def test_resolver_uses_validated_content_and_real_persistence_timestamp(context):
    _, repository, record, cutoff, forecast_at, _ = context
    service = PersistedMacroForecastInputService(repository)
    inputs = service.resolve(observation_keys=[record["observation_key"]],
                             knowledge_cutoff=cutoff, forecast_available_at=forecast_at)
    assert inputs[0]["sourceRef"] == service.PREFIX + record["observation_key"]
    assert inputs[0]["availableAt"] == record["created_at"]
    assert len(inputs[0]["contentHash"]) == 64
    assert inputs[0]["contentHash"] != record["observation_key"]


def test_old_publication_does_not_rescue_late_physical_persistence(context):
    _, repository, record, cutoff, forecast_at, _ = context
    service = PersistedMacroForecastInputService(repository)
    with pytest.raises(ValueError, match="publicada y persistida"):
        service.resolve(observation_keys=[record["observation_key"]],
                        knowledge_cutoff=cutoff - timedelta(seconds=2), forecast_available_at=forecast_at)


@pytest.mark.parametrize("keys", [[], ["missing"], ["a" * 64, "A" * 64], ["a" * 64] * 201])
def test_resolver_rejects_empty_malformed_duplicate_and_oversized_selection(context, keys):
    _, repository, _, cutoff, forecast_at, _ = context
    with pytest.raises(ValueError):
        PersistedMacroForecastInputService(repository).resolve(
            observation_keys=keys, knowledge_cutoff=cutoff, forecast_available_at=forecast_at,
        )


def test_missing_observation_fails_closed(context):
    _, repository, _, cutoff, forecast_at, _ = context
    with pytest.raises(ValueError, match="No existe"):
        PersistedMacroForecastInputService(repository).resolve(
            observation_keys=["a" * 64], knowledge_cutoff=cutoff, forecast_available_at=forecast_at,
        )


def test_resolver_rejects_database_content_tampering(context):
    database, repository, record, cutoff, forecast_at, _ = context
    mutated = dict(record["artifact"], value=999)
    with database.connect() as connection:
        connection.execute("UPDATE athena_macro_pit_observations SET artifact_json = ?",
                           (json.dumps(mutated),))
    with pytest.raises(ValueError):
        PersistedMacroForecastInputService(repository).resolve(
            observation_keys=[record["observation_key"]], knowledge_cutoff=cutoff,
            forecast_available_at=forecast_at,
        )


def test_api_constructs_persisted_v3_manifest_and_rechecks_reads(monkeypatch, context):
    database, macro_repository, record, cutoff, forecast_at, cycle = context
    class Cycles:
        def get_by_hash(self, *, cycle_hash):
            assert cycle_hash == CYCLE_HASH
            return cycle
    spec_repository = RecommendationResearchEvaluationSpecificationRepository(
        database, now_provider=lambda: forecast_at,
    )
    monkeypatch.setattr(api, "cycle_repository", Cycles())
    monkeypatch.setattr(api, "specification_repository", spec_repository)
    service = PersistedMacroForecastInputService(macro_repository)
    monkeypatch.setattr(api, "persisted_macro_input_service", service)
    body = {
        "specificationId": "persisted-input-test", "horizonSeconds": 86400,
        "expectedTotalReturn": 0.01, "availableAt": forecast_at.isoformat(),
        "periodStart": (forecast_at + timedelta(days=1)).isoformat(),
        "source": "athena-test", "sourceRef": "urn:test:output", "method": "test-only",
        "macroObservationKeys": [record["observation_key"]],
    }
    client = TestClient(app)
    response = client.post(f"{api.router.prefix}/research-cycle/{CYCLE_HASH}/persisted-macro-evaluation-specification", json=body)
    assert response.status_code == 200
    artifact = response.json()["data"]
    assert artifact["artifactVersion"] == "research-evaluation-specification-v3"
    assert artifact["productionLearningEligible"] is False
    assert artifact["inputEvidence"] == service.resolve(
        observation_keys=body["macroObservationKeys"], knowledge_cutoff=cutoff,
        forecast_available_at=forecast_at,
    )
    service.verify_specification(artifact)
    with database.connect() as connection:
        connection.execute("UPDATE athena_macro_pit_observations SET created_at = ?",
                           ((cutoff - timedelta(microseconds=1)).isoformat(),))
    response = client.get(f"{api.router.prefix}/evaluation-specification/{artifact['specificationHash']}")
    assert response.status_code == 404


def test_manifest_cannot_claim_another_content_hash(context):
    _, repository, record, cutoff, forecast_at, _ = context
    service = PersistedMacroForecastInputService(repository)
    inputs = service.resolve(observation_keys=[record["observation_key"]],
                             knowledge_cutoff=cutoff, forecast_available_at=forecast_at)
    inputs[0]["contentHash"] = "a" * 64
    with pytest.raises(ValueError, match="originales"):
        service.verify_specification({"inputEvidence": inputs, "cycleAsOf": cutoff.isoformat(),
                                      "forecastEvidence": {"availableAt": forecast_at.isoformat()}})


def test_publication_after_cycle_cutoff_is_not_usable(context):
    _, repository, _, cutoff, forecast_at, _ = context
    artifact = RecommendationMacroPitObservationService().build_artifact(
        series_id="GDP", value=101, observed_at=cutoff - timedelta(days=60),
        available_at=cutoff + timedelta(microseconds=1), source_provider="fred_alfred",
        source_ref="urn:test:gdp-late-vintage", unit="index",
    )
    record = repository.append(artifact=artifact)
    with pytest.raises(ValueError, match="publicada y persistida"):
        PersistedMacroForecastInputService(repository).resolve(
            observation_keys=[record["observation_key"]], knowledge_cutoff=cutoff,
            forecast_available_at=forecast_at,
        )


def test_forecast_measurement_checks_persisted_inputs_before_calculation(monkeypatch):
    class Specifications:
        def get_by_hash(self, **kwargs):
            return {"artifact": {"inputEvidence": [{"sourceRef": PersistedMacroForecastInputService.PREFIX + "a" * 64}]}}
    class Outcomes:
        def get_by_hash(self, **kwargs):
            return {}
    class Verifier:
        uses_persisted_macro_inputs = staticmethod(PersistedMacroForecastInputService.uses_persisted_macro_inputs)
        def verify_specification(self, artifact):
            raise ValueError("inputs originales no verificables")
    class MustNotCalculate:
        def evaluate(self, **kwargs):
            pytest.fail("No debe calcular errores con inputs no verificables")
    monkeypatch.setattr(api, "specification_repository", Specifications())
    monkeypatch.setattr(api, "outcome_repository", Outcomes())
    monkeypatch.setattr(api, "persisted_macro_input_service", Verifier())
    monkeypatch.setattr(api, "error_service", MustNotCalculate())
    response = TestClient(app).post(f"{api.router.prefix}/forecast-error", json={
        "specificationHash": "b" * 64, "outcomeHash": "c" * 64,
    })
    assert response.status_code == 400
    assert "inputs originales" in response.json()["detail"]
