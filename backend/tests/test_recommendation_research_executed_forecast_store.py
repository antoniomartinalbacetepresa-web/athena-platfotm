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
