"""Synthetic preselection regressions; not productive longitudinal evidence."""
from datetime import timedelta
import json

import pytest

from app.services.recommendation_research_prospective_cohort_service import RecommendationResearchProspectiveCohortService
from test_recommendation_research_executed_forecast_store import context, setup_store, persist


def setup_cohort(context, tmp_path):
    store, runner, specification, raw = setup_store(context, tmp_path)
    persist(store, specification, raw)
    service = RecommendationResearchProspectiveCohortService(store=store, now_provider=lambda: context[4])
    return service, specification["specificationHash"], runner


def test_cohort_denominator_preserves_missing_evaluations(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    plan = service.register(cohort_id="prospective-test", specification_hashes=[ref])
    assert service.get(cohort_id="prospective-test") == plan
    coverage = service.coverage(cohort_id="prospective-test", evaluated_specification_hashes=[])
    assert coverage["selectedCount"] == 1
    assert coverage["missingSpecificationHashes"] == [ref]
    assert coverage["membershipComplete"] is False
    complete = service.coverage(cohort_id="prospective-test", evaluated_specification_hashes=[ref])
    assert complete["membershipComplete"] is True
    assert complete["outcomeEvidenceVerified"] is False
    assert complete["productionLearningEligible"] is False


def test_cohort_retry_after_maturity_preserves_original_seal(context, tmp_path):
    service, ref, runner = setup_cohort(context, tmp_path)
    plan = service.register(cohort_id="prospective-test", specification_hashes=[ref])
    service._now = lambda: context[4] + timedelta(days=3)
    assert service.register(cohort_id="prospective-test", specification_hashes=[ref]) == plan
    assert len(runner.calls) == 1


def test_late_preselection_is_rejected(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    service._now = lambda: context[4] + timedelta(days=3)
    with pytest.raises(ValueError, match="antes del inicio"):
        service.register(cohort_id="late", specification_hashes=[ref])


def test_preselection_rejects_duplicates_and_replacement(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    with pytest.raises(ValueError, match="duplicados"):
        service.register(cohort_id="duplicate", specification_hashes=[ref, ref])
    service.register(cohort_id="prospective-test", specification_hashes=[ref])
    with pytest.raises(ValueError, match="cambiar"):
        service.register(cohort_id="prospective-test", specification_hashes=["a" * 64])
    with pytest.raises(ValueError, match="ajenos"):
        service.coverage(cohort_id="prospective-test", evaluated_specification_hashes=["a" * 64])


def test_cohort_detects_tampering_and_missing_receipt(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    plan = service.register(cohort_id="prospective-test", specification_hashes=[ref])
    with service._store._database.connect() as connection:
        altered = dict(plan, method="altered-method")
        connection.execute("UPDATE athena_research_prospective_cohorts SET artifact_json = ?",
                           (json.dumps(altered),))
    with pytest.raises(ValueError, match="modificada"):
        service.get(cohort_id="prospective-test")
    with service._store._database.connect() as connection:
        connection.execute("UPDATE athena_research_prospective_cohorts SET artifact_json = ?", (json.dumps(plan),))
        connection.execute("DELETE FROM athena_research_model_execution_receipts")
    with pytest.raises(ValueError, match="no tiene model execution receipt"):
        service.get(cohort_id="prospective-test")
