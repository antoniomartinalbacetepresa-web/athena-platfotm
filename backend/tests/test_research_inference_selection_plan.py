"""Synthetic pre-inference plan contracts; no empirical OOS evidence."""
from datetime import timedelta

import pytest

from app.services.research_inference_selection_plan_service import ResearchInferenceSelectionPlanService
from test_recommendation_research_model_executor import context, setup_executor


def setup(context, tmp_path):
    executor, _, template, _ = setup_executor(context, tmp_path)
    service = ResearchInferenceSelectionPlanService(database=context[0], manifest_service=executor._manifest,
                                                   now_provider=lambda: context[4] - timedelta(seconds=1))
    return service, template


def test_plan_seals_intent_and_retries_without_replacing_universe(context, tmp_path):
    service, template = setup(context, tmp_path)
    plan = service.register(plan_id="test-only", templates=[template], model_artifact_hash="a" * 64)
    assert service.get(plan_id="test-only") == plan
    assert plan["forecastEvidenceProduced"] is False
    assert plan["executionEnforcementImplemented"] is False
    service._now = lambda: context[4] + timedelta(days=3)
    assert service.register(plan_id="test-only", templates=[template], model_artifact_hash="a" * 64) == plan
    with pytest.raises(ValueError, match="replace"):
        service.register(plan_id="test-only", templates=[template], model_artifact_hash="b" * 64)


def test_late_or_duplicate_universe_fails_closed(context, tmp_path):
    service, template = setup(context, tmp_path)
    with pytest.raises(ValueError, match="Duplicated"):
        service.register(plan_id="duplicate", templates=[template, template], model_artifact_hash="a" * 64)
    service._now = lambda: context[4] + timedelta(seconds=1)
    with pytest.raises(ValueError, match="precede"):
        service.register(plan_id="late", templates=[template], model_artifact_hash="a" * 64)


def test_plan_detects_index_tampering(context, tmp_path):
    service, template = setup(context, tmp_path)
    service.register(plan_id="test-only", templates=[template], model_artifact_hash="a" * 64)
    with context[0].connect() as connection:
        connection.execute("UPDATE athena_research_inference_selection_plans SET plan_hash = ?", ("b" * 64,))
    with pytest.raises(ValueError, match="modified"):
        service.get(plan_id="test-only")
