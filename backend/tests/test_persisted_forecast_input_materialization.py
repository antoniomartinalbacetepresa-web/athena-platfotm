"""Synthetic executable-input regressions, not real OOS/production evidence."""
from datetime import datetime, timedelta
import hashlib
import json

import pytest

from app.services.persisted_forecast_input_manifest_service import PersistedForecastInputManifestService
from app.services.persisted_macro_forecast_input_service import PersistedMacroForecastInputService
from app.services.persisted_market_forecast_input_service import PersistedMarketForecastInputService
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from test_persisted_macro_forecast_inputs import context
from test_persisted_market_forecast_inputs import _context, _selection


def canonical_hash(content):
    return hashlib.sha256(json.dumps(
        content, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def setup_inputs(context, tmp_path, family):
    _, macro_repository, record, cutoff, forecast_at, cycle = context
    market_db, market_repository, instrument, observed, _ = _context(tmp_path)
    service = PersistedForecastInputManifestService(
        PersistedMacroForecastInputService(macro_repository),
        PersistedMarketForecastInputService(market_repository),
    )
    inputs = service.resolve(
        macro_observation_keys=[record["observation_key"]] if family != "market" else [],
        market_selections=[_selection(instrument, observed)] if family != "macro" else [],
        knowledge_cutoff=cutoff, forecast_available_at=forecast_at,
    )
    artifact = RecommendationResearchEvaluationSpecificationService().build(
        specification_id="materialized-inputs", cycle_record=cycle,
        horizon_seconds=86400, expected_total_return=0.01,
        available_at=forecast_at, source="athena-test", source_ref="urn:test:output",
        method="synthetic-only", period_start=forecast_at + timedelta(days=1),
        input_evidence=inputs,
    )
    return service, artifact, market_db


@pytest.mark.parametrize("family", ["macro", "market", "mixed"])
def test_materialization_delivers_exact_hashed_payloads(context, tmp_path, family):
    service, artifact, _ = setup_inputs(context, tmp_path, family)
    snapshot = service.materialize_specification(artifact)
    assert snapshot["specificationHash"] == artifact["specificationHash"]
    assert snapshot["inputManifestHash"] == canonical_hash(artifact["inputEvidence"])
    assert [item["evidence"] for item in snapshot["inputs"]] == artifact["inputEvidence"]
    for item in snapshot["inputs"]:
        assert canonical_hash(item["content"]) == item["evidence"]["contentHash"]
        if item["evidence"]["sourceRef"].startswith(service._macro.PREFIX):
            assert item["content"]["artifact"]["value"] == 100
        else:
            assert item["content"]["close"] == 100


def test_materialized_snapshot_is_detached_and_does_not_rewrite_inputs(context, tmp_path):
    service, artifact, _ = setup_inputs(context, tmp_path, "mixed")
    snapshot = service.materialize_specification(artifact)
    snapshot["inputs"][0]["content"].clear()
    snapshot["inputs"][0]["evidence"]["contentHash"] = "a" * 64
    rebuilt = service.materialize_specification(artifact)
    assert rebuilt["inputs"][0]["content"]
    assert rebuilt["inputs"][0]["evidence"] == artifact["inputEvidence"][0]


def test_materialization_rejects_market_mutation_after_sealing(context, tmp_path):
    service, artifact, database = setup_inputs(context, tmp_path, "market")
    with database.connect() as connection:
        connection.execute("UPDATE market_observations SET close = 999")
    with pytest.raises(ValueError, match="no coincide"):
        service.materialize_specification(artifact)


def test_materialization_rejects_missing_market_record(context, tmp_path):
    service, artifact, database = setup_inputs(context, tmp_path, "market")
    with database.connect() as connection:
        connection.execute("DELETE FROM market_observations")
    with pytest.raises(ValueError, match="no existe"):
        service.materialize_specification(artifact)


def test_materialization_validates_specification_before_loading(context, tmp_path):
    service, artifact, _ = setup_inputs(context, tmp_path, "mixed")
    artifact["expectedValue"] = 0.99
    with pytest.raises(ValueError):
        service.materialize_specification(artifact)


def test_materialization_rejects_macro_persistence_mutation(context, tmp_path):
    service, artifact, _ = setup_inputs(context, tmp_path, "macro")
    database, _, record, _, _, _ = context
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_macro_pit_observations SET created_at = ?",
            ((datetime.fromisoformat(record["created_at"]) + timedelta(microseconds=1)).isoformat(),),
        )
    with pytest.raises(ValueError, match="no coincide"):
        service.materialize_specification(artifact)


def test_materialization_rejects_declared_unresolvable_namespace(context, tmp_path):
    service, artifact, _ = setup_inputs(context, tmp_path, "macro")
    artifact["inputEvidence"][0]["sourceRef"] = "urn:test:declared-input"
    core_keys = (
        "artifactVersion", "specificationId", "cycleHash", "instrumentId", "symbol",
        "cycleAsOf", "metric", "periodStart", "periodEnd", "horizonSeconds",
        "expectedValue", "forecastEvidence", "inputEvidence",
    )
    artifact["specificationHash"] = canonical_hash({key: artifact[key] for key in core_keys})
    with pytest.raises(ValueError, match="no materializables"):
        service.materialize_specification(artifact)
