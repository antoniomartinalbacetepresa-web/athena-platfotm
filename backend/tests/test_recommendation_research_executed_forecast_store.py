"""Synthetic E2E execution/storage tests; not longitudinal product evidence."""
import hashlib

import pytest

from app.api import recommendation_research_forecast_evaluation as api
from app.services.recommendation_research_executed_forecast_store_service import RecommendationResearchExecutedForecastStoreService
from test_recommendation_research_model_executor import context, setup_executor


def setup_store(context, tmp_path):
    executor, runner, specification, raw = setup_executor(context, tmp_path)
    store = RecommendationResearchExecutedForecastStoreService(
        database=context[0], executor=executor, now_provider=lambda: context[4],
    )
    return store, runner, specification, raw


def persist(store, specification, raw):
    return store.execute_and_persist(
        specification=specification, model_bytes=raw,
        pinned_artifact_hash=hashlib.sha256(raw).hexdigest(),
    )


def test_inference_generated_forecast_is_sealed_once(context, tmp_path):
    import json
    store, runner, template, raw = setup_store(context, tmp_path)
    model = json.loads(raw)
    model["coefficient"] = 0.0002
    raw = json.dumps(model).encode()
    result = store.generate_and_persist(specification_template=template, model_bytes=raw,
                                       pinned_artifact_hash=hashlib.sha256(raw).hexdigest())
    final = result["specification"]["artifact"]
    assert final["expectedValue"] == 0.02
    assert result["receipt"]["artifact"]["output"]["expectedValue"] == 0.02
    assert template["expectedValue"] == 0.01
    assert persist(store, final, raw)["reused"] is True
    with pytest.raises(ValueError, match="identidad prospectiva nueva"):
        store.generate_and_persist(specification_template=template, model_bytes=raw,
                                   pinned_artifact_hash=hashlib.sha256(raw).hexdigest())
    assert len(runner.calls) == 1


def test_observed_execution_atomic_storage_and_gate(context, tmp_path, monkeypatch):
    store, runner, specification, raw = setup_store(context, tmp_path)
    result = persist(store, specification, raw)
    assert len(runner.calls) == 1
    receipt = result["receipt"]["artifact"]
    assert receipt["artifactVersion"] == "research-model-execution-receipt-v2"
    assert receipt["output"]["expectedValue"] == 0.01
    assert result["automaticTrading"] is False
    stored_spec = store.specifications.get_by_hash(specification_hash=specification["specificationHash"])
    stored_receipt = store.receipts.get_by_specification_hash(
        specification_hash=specification["specificationHash"], specification_record=stored_spec,
    )
    assert stored_receipt == result["receipt"]
    monkeypatch.setattr(api, "model_execution_receipt_repository", store.receipts)
    api._verify_model_execution_receipt_if_required(stored_spec)


def test_receipt_write_failure_rolls_back_specification(context, tmp_path, monkeypatch):
    store, _, specification, raw = setup_store(context, tmp_path)

    def unavailable(**kwargs):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(store.receipts, "append", unavailable)
    with pytest.raises(RuntimeError, match="storage failure"):
        persist(store, specification, raw)
    with pytest.raises(ValueError, match="No existe"):
        store.specifications.get_by_hash(specification_hash=specification["specificationHash"])
    with context[0].connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM athena_research_model_execution_receipts").fetchone()[0] == 0


def test_public_repository_path_cannot_mint_observed_receipt(context, tmp_path):
    store, _, specification, raw = setup_store(context, tmp_path)
    result = persist(store, specification, raw)
    with pytest.raises(ValueError, match="flujo interno"):
        store.receipts.append(artifact=result["receipt"]["artifact"], specification_record=result["specification"])


def test_persisted_model_byte_tampering_invalidates_receipt(context, tmp_path):
    store, _, specification, raw = setup_store(context, tmp_path)
    result = persist(store, specification, raw)
    tampered = result["receipt"]["artifact"]
    tampered["modelBytesBase64"] = "e30="
    # Even a newly hashed wrapper must fail its model/execution contract.
    tampered["receiptHash"] = store.receipt_service._canonical_hash(store.receipt_service._v2_core(tampered))
    with pytest.raises(ValueError):
        store.receipt_service.validate_against_specification(
            artifact=tampered, specification_record=result["specification"],
        )


def test_prevalidated_snapshot_cannot_substitute_altered_payloads(context, tmp_path):
    store, _, specification, raw = setup_store(context, tmp_path)
    result = persist(store, specification, raw)
    snapshot = store._executor._manifest.materialize_specification(specification)
    snapshot["inputs"][0]["content"].clear()
    with pytest.raises(ValueError, match="payloads modificados"):
        store.receipt_service.validate_against_specification(
            artifact=result["receipt"]["artifact"], specification_record=result["specification"],
            materialized_snapshot=snapshot,
        )


def test_workflow_retry_after_maturity_reuses_execution_without_runner(context, tmp_path):
    from datetime import timedelta
    store, runner, specification, raw = setup_store(context, tmp_path)
    first = persist(store, specification, raw)
    store._now = lambda: context[4] + timedelta(days=3)
    retry = persist(store, specification, raw)
    assert retry["reused"] is True
    assert first["reused"] is False
    assert retry["receipt"] == first["receipt"]
    assert retry["specification"] == first["specification"]
    assert len(runner.calls) == 1


def test_workflow_retry_rejects_changed_model_bytes(context, tmp_path):
    import json
    store, runner, specification, raw = setup_store(context, tmp_path)
    persist(store, specification, raw)
    changed = json.loads(raw)
    changed["coefficient"] = 0.001
    with pytest.raises(ValueError, match="bytes del modelo original"):
        persist(store, specification, json.dumps(changed).encode())
    assert len(runner.calls) == 1


def test_workflow_retry_does_not_recreate_missing_receipt(context, tmp_path):
    store, runner, specification, raw = setup_store(context, tmp_path)
    persist(store, specification, raw)
    with context[0].connect() as connection:
        connection.execute("DELETE FROM athena_research_model_execution_receipts")
    with pytest.raises(ValueError, match="no tiene model execution receipt"):
        persist(store, specification, raw)
    assert len(runner.calls) == 1


def test_workflow_retry_requires_correct_deployment_pin(context, tmp_path):
    store, runner, specification, raw = setup_store(context, tmp_path)
    persist(store, specification, raw)
    with pytest.raises(ValueError, match="artefacto fijado"):
        store.execute_and_persist(specification=specification, model_bytes=raw, pinned_artifact_hash="a" * 64)
    assert len(runner.calls) == 1


def test_conflicting_cycle_horizon_is_rejected_before_inference(context, tmp_path):
    from copy import deepcopy
    from app.services.recommendation_research_evaluation_specification_service import RecommendationResearchEvaluationSpecificationService
    store, runner, specification, raw = setup_store(context, tmp_path)
    first = persist(store, specification, raw)
    changed = deepcopy(specification)
    changed["specificationId"] = "another-prospective-forecast"
    service = RecommendationResearchEvaluationSpecificationService()
    keys = ("artifactVersion", "specificationId", "cycleHash", "instrumentId", "symbol", "cycleAsOf", "metric", "periodStart", "periodEnd", "horizonSeconds", "expectedValue", "forecastEvidence", "inputEvidence")
    changed["specificationHash"] = service._canonical_hash({key: changed[key] for key in keys})
    with pytest.raises(ValueError, match="ciclo/horizonte"):
        persist(store, changed, raw)
    assert len(runner.calls) == 1
    assert persist(store, specification, raw)["receipt"] == first["receipt"]
