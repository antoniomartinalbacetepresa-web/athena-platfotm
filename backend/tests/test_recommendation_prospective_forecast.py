"""Deterministic test evidence only; no production forecasts or approvals."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import recommendation_research_forecast_evaluation as api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_research_evaluation_specification_repository import (
    RecommendationResearchEvaluationSpecificationRepository,
)
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from app.services.recommendation_research_forecast_error_service import RecommendationResearchForecastErrorService
from app.services.recommendation_research_forecast_error_oos_summary_service import RecommendationResearchForecastErrorOosSummaryService
from app.repositories.recommendation_research_forecast_error_repository import RecommendationResearchForecastErrorRepository
from app.repositories.recommendation_research_outcome_attribution_repository import RecommendationResearchOutcomeAttributionRepository
from app.services.recommendation_research_outcome_attribution_service import RecommendationResearchOutcomeAttributionService
from test_recommendation_research_forecast_evaluation import CYCLE_AS_OF, CYCLE_HASH, _cycle_record
from test_recommendation_research_outcome_attribution import _attribution, PERIOD_START, PERIOD_END
from test_recommendation_research_forecast_error_oos_summary_service import canonical_hash, dataset


START = CYCLE_AS_OF + timedelta(days=1)
HORIZON = 30 * 86400
SEALED = CYCLE_AS_OF + timedelta(minutes=5)


def _build(*, start=START, available=SEALED):
    return RecommendationResearchEvaluationSpecificationService().build(
        specification_id="prospective-test", cycle_record=_cycle_record(),
        horizon_seconds=HORIZON, expected_total_return=0.12, available_at=available,
        source="athena-test", source_ref="urn:test:prospective", method="prospective-test-model",
        period_start=start,
    )


def test_v2_preserves_research_cutoff_and_uses_explicit_later_start():
    artifact = _build()
    assert artifact["artifactVersion"] == "research-evaluation-specification-v2"
    assert artifact["cycleAsOf"] == CYCLE_AS_OF.isoformat()
    assert artifact["periodStart"] == START.isoformat()
    assert artifact["periodEnd"] == (START + timedelta(seconds=HORIZON)).isoformat()
    assert artifact["productionLearningEligible"] is False
    RecommendationResearchEvaluationSpecificationService().validate_artifact(artifact)


@pytest.mark.parametrize("start", [CYCLE_AS_OF, CYCLE_AS_OF - timedelta(seconds=1), START.replace(tzinfo=None)])
def test_v2_rejects_nonprospective_or_naive_start(start):
    with pytest.raises(ValueError):
        _build(start=start)


def test_v2_rejects_forecast_available_after_start():
    with pytest.raises(ValueError, match="period_start"):
        _build(available=START + timedelta(microseconds=1))


def test_repository_rejects_evidence_unavailable_at_seal(tmp_path):
    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "future-evidence.db"), now_provider=lambda: SEALED,
    )
    with pytest.raises(ValueError, match="disponible al sellarla"):
        repository.append(artifact=_build(available=SEALED + timedelta(microseconds=1)))


def test_v2_repository_prevents_moving_prospective_start(tmp_path):
    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "immutable-start.db"), now_provider=lambda: SEALED,
    )
    first = repository.append(artifact=_build())
    assert first["created_at"] == SEALED.isoformat()
    with pytest.raises(ValueError, match="contenido distinto"):
        repository.append(artifact=_build(start=START + timedelta(days=1)))


def test_v2_exact_outcome_error_and_oos_summary_lifecycle(tmp_path):
    database = AthenaDatabase(tmp_path / "lifecycle.db")
    repository = RecommendationResearchEvaluationSpecificationRepository(
        database, now_provider=lambda: SEALED,
    )
    specification = repository.append(artifact=_build(start=PERIOD_START))
    payload = RecommendationResearchOutcomeAttributionService().bind(
        outcome_id="prospective-outcome-test", cycle_record=_cycle_record(),
        attribution_payload=_attribution(),
    )
    outcome = RecommendationResearchOutcomeAttributionRepository(database).append(payload=payload)
    error = RecommendationResearchForecastErrorService().evaluate(
        specification_record=specification, outcome_record=outcome,
    )
    persisted_error = RecommendationResearchForecastErrorRepository(database).append(artifact=error)
    summary = RecommendationResearchForecastErrorOosSummaryService().build(
        summary_id="prospective-oos-test", as_of=datetime.fromisoformat(persisted_error["created_at"]),
        error_records=[persisted_error],
        specification_records=[specification],
    )
    assert summary["observationCount"] == 1
    assert summary["productionLearningEligible"] is False
    assert summary["policy"]["automaticTrading"] is False
    assert summary["rows"][0]["periodStart"] == PERIOD_START.isoformat()
    assert summary["rows"][0]["periodEnd"] == PERIOD_END.isoformat()


def test_prospective_api_seals_v2_without_rewriting_v1(monkeypatch, tmp_path):
    class CycleRepository:
        def get_by_hash(self, *, cycle_hash):
            assert cycle_hash == CYCLE_HASH
            return _cycle_record()

    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "api.db"), now_provider=lambda: SEALED,
    )
    monkeypatch.setattr(api, "cycle_repository", CycleRepository())
    monkeypatch.setattr(api, "specification_repository", repository)
    body = {
        "specificationId": "api-v2-test", "horizonSeconds": HORIZON,
        "expectedTotalReturn": 0.12, "availableAt": SEALED.isoformat(),
        "source": "athena-test", "sourceRef": "urn:test:api", "method": "prospective-test-model",
        "periodStart": START.isoformat(),
    }
    client = TestClient(app)
    response = client.post(f"{api.router.prefix}/research-cycle/{CYCLE_HASH}/prospective-evaluation-specification", json=body)
    assert response.status_code == 200
    assert response.json()["data"]["artifactVersion"] == "research-evaluation-specification-v2"
    assert response.json()["data"]["persistence"]["sealedAt"] == SEALED.isoformat()
    body.pop("periodStart")
    response = client.post(f"{api.router.prefix}/research-cycle/{CYCLE_HASH}/evaluation-specification", json=body)
    assert response.status_code == 400


def test_v2_cannot_be_relabelled_as_v1():
    artifact = _build()
    artifact["artifactVersion"] = "research-evaluation-specification-v1"
    with pytest.raises(ValueError, match="cycleAsOf"):
        RecommendationResearchEvaluationSpecificationService().validate_artifact(artifact)


def test_v2_rejects_fractional_horizon_mismatch():
    artifact = _build()
    end = datetime.fromisoformat(artifact["periodEnd"]) + timedelta(microseconds=1)
    artifact["periodEnd"] = end.isoformat()
    with pytest.raises(ValueError, match="horizonSeconds"):
        RecommendationResearchEvaluationSpecificationService().validate_artifact(artifact)


def test_oos_summary_does_not_pool_v1_and_v2_contracts():
    errors, specs = dataset()
    artifact = specs[0]["artifact"]
    artifact["artifactVersion"] = "research-evaluation-specification-v2"
    artifact["cycleAsOf"] = (datetime.fromisoformat(artifact["periodStart"]) - timedelta(days=1)).isoformat()
    artifact["policy"]["targetDefinition"] = "precommitted_before_or_at_prospective_period_start"
    artifact["policy"]["period"] = "starts_after_cycle_as_of_with_exact_elapsed_horizon"
    artifact["specificationHash"] = canonical_hash({key: artifact[key] for key in (
        "artifactVersion", "specificationId", "cycleHash", "instrumentId", "symbol",
        "cycleAsOf", "metric", "periodStart", "periodEnd", "horizonSeconds", "expectedValue", "forecastEvidence",
    )})
    specs[0]["specification_hash"] = artifact["specificationHash"]
    with pytest.raises(ValueError, match="contratos de forecast"):
        RecommendationResearchForecastErrorOosSummaryService().build(
            summary_id="mixed-contract-test", as_of=datetime(2026, 9, 1, tzinfo=CYCLE_AS_OF.tzinfo),
            error_records=errors, specification_records=specs,
        )
