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
from app.repositories.recommendation_research_model_execution_receipt_repository import (
    RecommendationResearchModelExecutionReceiptRepository,
)
from app.services.recommendation_research_model_execution_receipt_service import (
    RecommendationResearchModelExecutionReceiptService,
)
from test_recommendation_pit_input_forecast import INPUT_AVAILABLE, SEALED, START, _build


EXECUTED = INPUT_AVAILABLE + timedelta(minutes=1)
MODEL_HASH = "c" * 64


def _specification_record():
    artifact = _build()
    return {
        "specification_hash": artifact["specificationHash"],
        "artifact": artifact,
        "created_at": SEALED.isoformat(),
    }


def _receipt(*, record=None, executed_at=EXECUTED, model_name="athena-total-return"):
    specification_record = record or _specification_record()
    return RecommendationResearchModelExecutionReceiptService().build(
        specification_record=specification_record,
        execution_id="execution-test-v1",
        model_name=model_name,
        model_version="2026.09.14-test",
        model_artifact_hash=MODEL_HASH,
        executed_at=executed_at,
    )


def test_receipt_binds_model_inputs_and_total_return_output():
    record = _specification_record()
    artifact = _receipt(record=record)
    assert artifact["artifactVersion"] == "research-model-execution-receipt-v1"
    assert artifact["specificationHash"] == record["specification_hash"]
    assert artifact["output"] == {"metric": "total_return", "expectedValue": 0.12}
    assert artifact["model"]["artifactHash"] == MODEL_HASH
    assert artifact["productionEligible"] is False
    assert artifact["productionLearningEligible"] is False
    assert artifact["automaticTrading"] is False
    assert artifact["policy"]["modelQualityClaim"] == "forbidden"
    RecommendationResearchModelExecutionReceiptService().validate_against_specification(
        artifact=artifact,
        specification_record=record,
    )


@pytest.mark.parametrize("seal", [
    None,
    "2026-01-01T00:00:00",
    (SEALED - timedelta(days=365)).isoformat(),
    (START + timedelta(microseconds=1)).isoformat(),
])
def test_receipt_rejects_missing_naive_early_or_late_specification_seal(seal):
    record = _specification_record()
    record["created_at"] = seal
    with pytest.raises(ValueError):
        _receipt(record=record)


def test_receipt_revalidation_checks_specification_physical_seal():
    record = _specification_record()
    receipt = _receipt(record=record)
    record["created_at"] = (START + timedelta(microseconds=1)).isoformat()
    with pytest.raises(ValueError, match="sello físico"):
        RecommendationResearchModelExecutionReceiptService().validate_against_specification(
            artifact=receipt, specification_record=record,
        )


def test_identical_receipt_retry_after_maturity_preserves_original_record(tmp_path):
    database = AthenaDatabase(tmp_path / "receipt-retry.db")
    record = RecommendationResearchEvaluationSpecificationRepository(
        database, now_provider=lambda: SEALED,
    ).append(artifact=_build())
    receipt = _receipt(record=record)
    first = RecommendationResearchModelExecutionReceiptRepository(
        database, now_provider=lambda: SEALED,
    ).append(artifact=receipt, specification_record=record)

    def must_not_resample_time():
        pytest.fail("An identical retry must use its original physical seal.")

    retry_repository = RecommendationResearchModelExecutionReceiptRepository(
        database, now_provider=must_not_resample_time,
    )
    retry = retry_repository.append(artifact=receipt, specification_record=record)
    assert retry == first
    assert retry["created_at"] == SEALED.isoformat()
    late_retry = RecommendationResearchModelExecutionReceiptRepository(
        database, now_provider=lambda: START + timedelta(days=1),
    ).append(artifact=receipt, specification_record=record)
    assert late_retry == first


def test_new_receipt_after_period_start_stays_blocked(tmp_path):
    record = _specification_record()
    repository = RecommendationResearchModelExecutionReceiptRepository(
        AthenaDatabase(tmp_path / "receipt-late.db"),
        now_provider=lambda: START + timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="antes o al inicio"):
        repository.append(artifact=_receipt(record=record), specification_record=record)


def test_repository_rejects_receipt_persisted_before_specification_seal(tmp_path):
    record = _specification_record()
    repository = RecommendationResearchModelExecutionReceiptRepository(
        AthenaDatabase(tmp_path / "receipt-before-spec.db"),
        now_provider=lambda: SEALED - timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="antes del sello"):
        repository.append(artifact=_receipt(record=record), specification_record=record)


def test_receipt_read_rejects_tampered_persistence_before_specification(tmp_path):
    database = AthenaDatabase(tmp_path / "receipt-seal-tamper.db")
    record = _specification_record()
    repository = RecommendationResearchModelExecutionReceiptRepository(
        database, now_provider=lambda: SEALED,
    )
    receipt = _receipt(record=record)
    repository.append(artifact=receipt, specification_record=record)
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_model_execution_receipts SET created_at = ?",
            ((SEALED - timedelta(microseconds=1)).isoformat(),),
        )
    with pytest.raises(ValueError, match="orden temporal"):
        repository.get_by_hash(receipt_hash=receipt["receiptHash"], specification_record=record)


def test_concurrent_identical_receipt_writes_are_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database = AthenaDatabase(tmp_path / "receipt-concurrent.db")
    record = _specification_record()
    receipt = _receipt(record=record)
    repository = RecommendationResearchModelExecutionReceiptRepository(
        database, now_provider=lambda: SEALED,
    )
    repository.initialize()
    barrier = Barrier(2)

    def write():
        barrier.wait(timeout=5)
        return repository.append(artifact=receipt, specification_record=record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: write(), range(2)))
    assert first == second
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM athena_research_model_execution_receipts"
        ).fetchone()[0] == 1


def test_receipt_rejects_execution_before_latest_input():
    with pytest.raises(ValueError, match="anterior a un input"):
        _receipt(executed_at=INPUT_AVAILABLE - timedelta(microseconds=1))


def test_receipt_rejects_execution_after_forecast_available_at():
    with pytest.raises(ValueError, match="posterior a forecastEvidence"):
        _receipt(executed_at=SEALED + timedelta(microseconds=1))


def test_receipt_rejects_non_v3_specification():
    record = _specification_record()
    record["artifact"].pop("inputEvidence")
    record["artifact"]["artifactVersion"] = "research-evaluation-specification-v2"
    with pytest.raises(ValueError):
        _receipt(record=record)


def test_receipt_rejects_fmp_model_identity():
    with pytest.raises(ValueError, match="FMP"):
        _receipt(model_name="Financial Modeling Prep model")


def test_receipt_detects_output_tampering():
    record = _specification_record()
    artifact = _receipt(record=record)
    artifact["output"]["expectedValue"] = 0.99
    with pytest.raises(ValueError, match="outputHash"):
        RecommendationResearchModelExecutionReceiptService().validate_artifact(artifact)


def test_receipt_detects_input_manifest_change_against_specification():
    record = _specification_record()
    artifact = _receipt(record=record)
    record["artifact"]["inputEvidence"][0]["contentHash"] = "d" * 64
    with pytest.raises(ValueError):
        RecommendationResearchModelExecutionReceiptService().validate_against_specification(
            artifact=artifact,
            specification_record=record,
        )


def test_repository_is_append_only_per_specification(tmp_path):
    database = AthenaDatabase(tmp_path / "execution-receipt.db")
    specification_repository = RecommendationResearchEvaluationSpecificationRepository(
        database,
        now_provider=lambda: SEALED,
    )
    specification_record = specification_repository.append(artifact=_build())
    repository = RecommendationResearchModelExecutionReceiptRepository(
        database,
        now_provider=lambda: SEALED,
    )
    first = repository.append(
        artifact=_receipt(record=specification_record),
        specification_record=specification_record,
    )
    assert first["created_at"] == SEALED.isoformat()
    loaded = repository.get_by_specification_hash(
        specification_hash=specification_record["specification_hash"],
        specification_record=specification_record,
    )
    assert loaded["receipt_hash"] == first["receipt_hash"]

    second = RecommendationResearchModelExecutionReceiptService().build(
        specification_record=specification_record,
        execution_id="execution-test-v2",
        model_name="athena-total-return",
        model_version="2026.09.14-test-2",
        model_artifact_hash="e" * 64,
        executed_at=EXECUTED,
    )
    with pytest.raises(ValueError, match="recibo de ejecución distinto"):
        repository.append(artifact=second, specification_record=specification_record)


def test_repository_rejects_receipt_persisted_before_execution(tmp_path):
    database = AthenaDatabase(tmp_path / "receipt-before-execution.db")
    specification_repository = RecommendationResearchEvaluationSpecificationRepository(
        database,
        now_provider=lambda: SEALED,
    )
    specification_record = specification_repository.append(artifact=_build())
    repository = RecommendationResearchModelExecutionReceiptRepository(
        database,
        now_provider=lambda: EXECUTED - timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="aún no había ocurrido"):
        repository.append(
            artifact=_receipt(record=specification_record),
            specification_record=specification_record,
        )


def test_api_round_trip_persists_and_revalidates_receipt(monkeypatch, tmp_path):
    database = AthenaDatabase(tmp_path / "receipt-api.db")
    specification_repository = RecommendationResearchEvaluationSpecificationRepository(
        database,
        now_provider=lambda: SEALED,
    )
    specification_record = specification_repository.append(artifact=_build())
    receipt_repository = RecommendationResearchModelExecutionReceiptRepository(
        database,
        now_provider=lambda: SEALED,
    )
    monkeypatch.setattr(api, "specification_repository", specification_repository)
    monkeypatch.setattr(api, "model_execution_receipt_repository", receipt_repository)

    client = TestClient(app)
    body = {
        "executionId": "api-execution-v1",
        "modelName": "athena-total-return",
        "modelVersion": "2026.09.14-test",
        "modelArtifactHash": MODEL_HASH,
        "executedAt": EXECUTED.isoformat(),
    }
    path = (
        f"{api.router.prefix}/evaluation-specification/"
        f"{specification_record['specification_hash']}/model-execution-receipt"
    )
    response = client.post(path, json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["specificationHash"] == specification_record["specification_hash"]
    assert data["persistence"]["appendOnly"] is True
    assert data["persistence"]["sealedAt"] == SEALED.isoformat()

    response = client.get(path)
    assert response.status_code == 200
    loaded = response.json()["data"]
    assert loaded["receiptHash"] == data["receiptHash"]
    assert loaded["output"] == {"metric": "total_return", "expectedValue": 0.12}


def test_api_rejects_naive_execution_timestamp(monkeypatch, tmp_path):
    database = AthenaDatabase(tmp_path / "receipt-api-naive.db")
    specification_repository = RecommendationResearchEvaluationSpecificationRepository(
        database,
        now_provider=lambda: SEALED,
    )
    specification_record = specification_repository.append(artifact=_build())
    monkeypatch.setattr(api, "specification_repository", specification_repository)
    monkeypatch.setattr(
        api,
        "model_execution_receipt_repository",
        RecommendationResearchModelExecutionReceiptRepository(
            database,
            now_provider=lambda: SEALED,
        ),
    )
    response = TestClient(app).post(
        f"{api.router.prefix}/evaluation-specification/{specification_record['specification_hash']}/model-execution-receipt",
        json={
            "executionId": "api-naive",
            "modelName": "athena-total-return",
            "modelVersion": "test",
            "modelArtifactHash": MODEL_HASH,
            "executedAt": EXECUTED.replace(tzinfo=None).isoformat(),
        },
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
