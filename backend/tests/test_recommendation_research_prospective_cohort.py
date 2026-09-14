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
    assert plan["artifactVersion"] == "research-prospective-cohort-v2"
    assert set(plan["modelIdentity"]) == {"name", "version", "artifactHash"}
    assert service.get(cohort_id="prospective-test") == plan
    coverage = service.coverage(cohort_id="prospective-test", evaluated_specification_hashes=[])
    assert coverage["selectedCount"] == 1
    assert coverage["missingSpecificationHashes"] == [ref]
    assert coverage["membershipComplete"] is False
    complete = service.coverage(cohort_id="prospective-test", evaluated_specification_hashes=[ref])
    assert complete["membershipComplete"] is True
    assert complete["outcomeEvidenceVerified"] is False
    assert complete["productionLearningEligible"] is False


def test_cohort_detects_consistent_receipt_model_replacement(context, tmp_path, monkeypatch):
    from copy import deepcopy
    service, ref, _ = setup_cohort(context, tmp_path)
    service.register(cohort_id="pinned", specification_hashes=[ref])
    record = service._specifications.get_by_hash(specification_hash=ref)
    receipt = service._receipts.get_by_specification_hash(specification_hash=ref, specification_record=record)
    replacement = deepcopy(receipt)
    replacement["artifact"]["model"]["artifactHash"] = "b" * 64
    monkeypatch.setattr(service._receipts, "get_by_specification_hash", lambda **kwargs: deepcopy(replacement))
    with pytest.raises(ValueError, match="identidad de modelo sellada"):
        service.get(cohort_id="pinned")


def test_legacy_cohort_remains_readable_without_fabricating_model_pin(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    plan = service.register(cohort_id="legacy", specification_hashes=[ref])
    core = {k: v for k, v in plan.items() if k not in ("cohortHash", "modelIdentity")}
    core["artifactVersion"] = "research-prospective-cohort-v1"
    legacy = dict(core, cohortHash=service._hash(core))
    with service._database.connect() as connection:
        connection.execute("UPDATE athena_research_prospective_cohorts SET artifact_json = ?, cohort_hash = ?",
                           (json.dumps(legacy), legacy["cohortHash"]))
    assert service.get(cohort_id="legacy") == legacy
    assert "modelIdentity" not in service.register(cohort_id="legacy", specification_hashes=[ref])


def test_read_only_cohort_resolves_observed_receipt_without_configuring_runner(context, tmp_path, monkeypatch):
    import app.services.recommendation_research_prospective_cohort_service as module
    import app.services.persisted_market_forecast_input_service as market_module

    service, ref, runner = setup_cohort(context, tmp_path)
    plan = service.register(cohort_id="prospective-test", specification_hashes=[ref])
    monkeypatch.setattr(module, "AthenaDatabase", lambda: service._database)
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(service._database.database_path))
    monkeypatch.setattr(market_module, "MarketObservationRepository", lambda: service._store._executor._manifest._market._repository)
    reader = RecommendationResearchProspectiveCohortService()
    assert reader.get(cohort_id="prospective-test") == plan
    assert len(runner.calls) == 1


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


@pytest.mark.parametrize("changed_field", ["name", "version", "artifactHash", None])
def test_cohort_binds_one_model_identity_across_selected_forecasts(context, tmp_path, changed_field):
    from copy import deepcopy
    service, ref, _ = setup_cohort(context, tmp_path)
    original = service._specifications.get_by_hash(specification_hash=ref)
    receipt = service._receipts.get_by_specification_hash(specification_hash=ref, specification_record=original)

    class Specifications:
        def get_by_hash(self, **kwargs):
            return deepcopy(original)

    class Receipts:
        def get_by_specification_hash(self, **kwargs):
            result = deepcopy(receipt)
            if kwargs["specification_hash"] == "b" * 64 and changed_field:
                result["artifact"]["model"][changed_field] = "b" * 64 if changed_field == "artifactHash" else "changed"
            return result

    service._specifications, service._receipts = Specifications(), Receipts()
    if changed_field is None:
        assert len(service._forecasts(["a" * 64, "b" * 64])) == 2
    else:
        with pytest.raises(ValueError, match="artefacto de modelo"):
            service._forecasts(["a" * 64, "b" * 64])
