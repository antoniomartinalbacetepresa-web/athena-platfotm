"""Deterministic software regressions only; not production forecast evidence."""
from datetime import timedelta

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
from test_recommendation_prospective_forecast import HORIZON, SEALED, START
from test_recommendation_research_forecast_evaluation import CYCLE_HASH, _cycle_record


INPUT_AVAILABLE = SEALED - timedelta(minutes=2)
INPUT_HASH = "a" * 64
SECOND_INPUT_HASH = "b" * 64


def _inputs(*, available=INPUT_AVAILABLE, source="yahoo-finance", content_hash=INPUT_HASH):
    return [
        {
            "source": source,
            "sourceRef": "urn:athena:test:pit-input",
            "availableAt": available,
            "contentHash": content_hash,
        }
    ]


def _build(*, inputs=None, forecast_available=SEALED):
    return RecommendationResearchEvaluationSpecificationService().build(
        specification_id="pit-input-test",
        cycle_record=_cycle_record(),
        horizon_seconds=HORIZON,
        expected_total_return=0.12,
        available_at=forecast_available,
        source="athena-test",
        source_ref="urn:test:pit-output",
        method="pit-bound-test-model",
        period_start=START,
        input_evidence=_inputs() if inputs is None else inputs,
    )


def test_v3_binds_input_content_hash_and_temporal_provenance():
    artifact = _build()
    assert artifact["artifactVersion"] == "research-evaluation-specification-v3"
    assert artifact["inputEvidence"] == [
        {
            "source": "yahoo-finance",
            "sourceRef": "urn:athena:test:pit-input",
            "availableAt": INPUT_AVAILABLE.isoformat(),
            "contentHash": INPUT_HASH,
        }
    ]
    assert artifact["productionLearningEligible"] is False
    assert artifact["policy"]["automaticProductionPromotion"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert artifact["policy"]["inputQualityClaim"] == "forbidden"
    RecommendationResearchEvaluationSpecificationService().validate_artifact(artifact)


def test_v3_rejects_input_that_appeared_after_forecast_output():
    with pytest.raises(ValueError, match="disponible al generar"):
        _build(inputs=_inputs(available=SEALED + timedelta(microseconds=1)))


def test_v3_rejects_duplicate_input_content_hashes():
    inputs = _inputs()
    inputs.append(
        {
            "source": "sec",
            "sourceRef": "urn:athena:test:duplicate",
            "availableAt": INPUT_AVAILABLE,
            "contentHash": INPUT_HASH,
        }
    )
    with pytest.raises(ValueError, match="duplicado"):
        _build(inputs=inputs)


def test_v3_rejects_forbidden_fmp_input_source():
    with pytest.raises(ValueError, match="FMP"):
        _build(inputs=_inputs(source="Financial Modeling Prep"))


def test_v3_rejects_empty_input_manifest():
    with pytest.raises(ValueError, match="al menos una"):
        _build(inputs=[])


def test_v3_detects_post_seal_input_manifest_tampering():
    artifact = _build()
    artifact["inputEvidence"][0]["contentHash"] = SECOND_INPUT_HASH
    with pytest.raises(ValueError, match="modificada"):
        RecommendationResearchEvaluationSpecificationService().validate_artifact(artifact)


def test_v3_repository_persists_same_append_only_specification_path(tmp_path):
    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "pit-input.db"),
        now_provider=lambda: SEALED,
    )
    persisted = repository.append(artifact=_build())
    assert persisted["created_at"] == SEALED.isoformat()
    loaded = repository.get_by_hash(specification_hash=persisted["specification_hash"])
    assert loaded["artifact"]["artifactVersion"] == "research-evaluation-specification-v3"
    assert loaded["artifact"]["inputEvidence"][0]["contentHash"] == INPUT_HASH


def test_v3_api_requires_and_persists_pit_input_manifest(monkeypatch, tmp_path):
    class CycleRepository:
        def get_by_hash(self, *, cycle_hash):
            assert cycle_hash == CYCLE_HASH
            return _cycle_record()

    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "pit-api.db"),
        now_provider=lambda: SEALED,
    )
    monkeypatch.setattr(api, "cycle_repository", CycleRepository())
    monkeypatch.setattr(api, "specification_repository", repository)
    body = {
        "specificationId": "api-v3-test",
        "horizonSeconds": HORIZON,
        "expectedTotalReturn": 0.12,
        "availableAt": SEALED.isoformat(),
        "source": "athena-test",
        "sourceRef": "urn:test:api-v3",
        "method": "pit-bound-test-model",
        "periodStart": START.isoformat(),
        "inputEvidence": [
            {
                "source": "yahoo-finance",
                "sourceRef": "urn:athena:test:api-input",
                "availableAt": INPUT_AVAILABLE.isoformat(),
                "contentHash": INPUT_HASH,
            }
        ],
    }
    client = TestClient(app)
    response = client.post(
        f"{api.router.prefix}/research-cycle/{CYCLE_HASH}/pit-safe-prospective-evaluation-specification",
        json=body,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifactVersion"] == "research-evaluation-specification-v3"
    assert data["inputEvidence"][0]["contentHash"] == INPUT_HASH
    assert data["persistence"]["sealedAt"] == SEALED.isoformat()


def test_v3_api_rejects_naive_input_timestamp(monkeypatch, tmp_path):
    class CycleRepository:
        def get_by_hash(self, *, cycle_hash):
            return _cycle_record()

    monkeypatch.setattr(api, "cycle_repository", CycleRepository())
    monkeypatch.setattr(
        api,
        "specification_repository",
        RecommendationResearchEvaluationSpecificationRepository(
            AthenaDatabase(tmp_path / "pit-api-naive.db"), now_provider=lambda: SEALED
        ),
    )
    body = {
        "specificationId": "api-v3-naive-test",
        "horizonSeconds": HORIZON,
        "expectedTotalReturn": 0.12,
        "availableAt": SEALED.isoformat(),
        "source": "athena-test",
        "sourceRef": "urn:test:api-v3-naive",
        "method": "pit-bound-test-model",
        "periodStart": START.isoformat(),
        "inputEvidence": [
            {
                "source": "yahoo-finance",
                "sourceRef": "urn:athena:test:naive-input",
                "availableAt": INPUT_AVAILABLE.replace(tzinfo=None).isoformat(),
                "contentHash": INPUT_HASH,
            }
        ],
    }
    client = TestClient(app)
    response = client.post(
        f"{api.router.prefix}/research-cycle/{CYCLE_HASH}/pit-safe-prospective-evaluation-specification",
        json=body,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
