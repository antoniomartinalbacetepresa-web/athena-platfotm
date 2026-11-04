"""Synthetic planned coverage regressions; never production OOS evidence."""
from datetime import timedelta
import hashlib

import pytest

from app.services.research_inference_plan_coverage_service import ResearchInferencePlanCoverageService
from app.services.research_inference_selection_plan_service import ResearchInferenceSelectionPlanService
from test_recommendation_research_executed_forecast_store import context, setup_store, persist


def setup(context, tmp_path, *, late_plan=False, different_model=False):
    store, runner, template, raw = setup_store(context, tmp_path)
    pin = hashlib.sha256(raw).hexdigest()
    plans = ResearchInferenceSelectionPlanService(
        database=context[0], manifest_service=store._executor._manifest,
        now_provider=lambda: context[4] - timedelta(milliseconds=50 if late_plan else 500))
    plan = plans.register(plan_id="test-only", templates=[template],
                          model_artifact_hash="b" * 64 if different_model else pin)
    coverage = ResearchInferencePlanCoverageService(
        database=context[0], plans=plans, specifications=store.specifications, receipts=store.receipts)
    return store, runner, template, raw, plan, coverage


def test_missing_generation_remains_in_denominator(context, tmp_path):
    _, runner, template, _, plan, coverage = setup(context, tmp_path)
    report = coverage.build(plan_id="test-only")
    assert report["selectedCount"] == 1
    assert report["generatedCount"] == 0
    assert report["missingTemplateHashes"] == [template["specificationHash"]]
    assert report["generationComplete"] is False
    assert report["outcomeEvidenceVerified"] is False
    assert runner.calls == []


def test_observed_generation_binds_plan_template_and_receipt(context, tmp_path):
    store, runner, template, raw, plan, coverage = setup(context, tmp_path)
    result = persist(store, template, raw)
    report = coverage.build(plan_id="test-only")
    assert report["planHash"] == plan["planHash"]
    assert report["generatedCount"] == report["selectedCount"] == 1
    assert report["generated"][0]["receiptHash"] == result["receipt"]["artifact"]["receiptHash"]
    assert report["generationComplete"] is True
    assert report["productionLearningEligible"] is False
    assert len(runner.calls) == 1


@pytest.mark.parametrize("failure", ["late_plan", "different_model"])
def test_unplanned_execution_cannot_be_counted(context, tmp_path, failure):
    store, _, template, raw, _, coverage = setup(context, tmp_path, **{failure: True})
    persist(store, template, raw)
    with pytest.raises(ValueError):
        coverage.build(plan_id="test-only")
