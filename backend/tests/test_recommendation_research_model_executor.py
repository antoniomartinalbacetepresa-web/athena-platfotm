"""Synthetic runner/software evidence only, never production/OOS performance."""
from datetime import timedelta
import hashlib
import json

import pytest

from app.services.recommendation_research_model_executor_service import RecommendationResearchModelExecutorService
from test_persisted_forecast_input_materialization import context, setup_inputs, canonical_hash


class SyntheticRunner:
    def __init__(self):
        self.calls = []

    def predict(self, *, model_bytes, inputs):
        self.calls.append((model_bytes, inputs))
        payload = inputs[0]["content"]
        value = payload["artifact"]["value"] if "artifact" in payload else payload["close"]
        return {"metric": "total_return", "expectedValue": value * json.loads(model_bytes)["coefficient"]}


def setup_executor(context, tmp_path, *, runner=None, model_metric="total_return", ticks=None):
    manifest, specification, _ = setup_inputs(context, tmp_path, "mixed")
    available = context[4]
    times = iter(ticks or [available - timedelta(milliseconds=100), available])
    runner = runner or SyntheticRunner()
    executor = RecommendationResearchModelExecutorService(
        runner=runner, manifest_service=manifest, now_provider=lambda: next(times),
    )
    model_bytes = json.dumps({
        "name": "synthetic-runner-model", "version": "test-only-v1",
        "metric": model_metric, "horizonSeconds": 86400, "coefficient": 0.0001,
    }).encode("utf-8")
    return executor, runner, specification, model_bytes


def execute(executor, specification, model_bytes):
    return executor.execute(
        specification=specification, model_bytes=model_bytes,
        pinned_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
    )


def test_executor_observes_real_runner_output_using_exact_bytes_and_payload(context, tmp_path):
    executor, runner, spec, raw = setup_executor(context, tmp_path)
    observed = execute(executor, spec, raw)
    assert runner.calls[0][0] is raw
    assert observed["model"]["artifactHash"] == hashlib.sha256(raw).hexdigest()
    assert observed["output"] == {"metric": "total_return", "expectedValue": 0.01}
    assert observed["outputHash"] == canonical_hash(observed["output"])
    assert observed["inputSnapshotHash"] == canonical_hash(runner.calls[0][1])
    assert observed["inputManifestHash"] == canonical_hash(spec["inputEvidence"])
    assert observed["executedAt"] == context[4].isoformat()
    assert observed["specificationHash"] == spec["specificationHash"]
    assert observed["productionEligible"] is False
    assert observed["automaticTrading"] is False
    # An observation is deliberately not a receipt-v2 and cannot open OOS.
    assert observed["artifactVersion"] != "research-model-execution-receipt-v2"


def test_executor_rejects_wrong_pinned_bytes_before_runner(context, tmp_path):
    executor, runner, spec, raw = setup_executor(context, tmp_path)
    with pytest.raises(ValueError, match="artefacto fijado"):
        executor.execute(specification=spec, model_bytes=raw, pinned_artifact_hash="a" * 64)
    assert runner.calls == []


def test_executor_rejects_execution_before_latest_input(context, tmp_path):
    available = context[4]
    executor, runner, spec, raw = setup_executor(
        context, tmp_path, ticks=[available - timedelta(days=1)],
    )
    with pytest.raises(ValueError, match="disponibilidad"):
        execute(executor, spec, raw)
    assert runner.calls == []


def test_executor_rejects_wrong_model_horizon(context, tmp_path):
    executor, runner, spec, raw = setup_executor(context, tmp_path)
    model = json.loads(raw)
    model["horizonSeconds"] = 3600
    with pytest.raises(ValueError, match="horizonte"):
        execute(executor, spec, json.dumps(model).encode())
    assert runner.calls == []


def test_executor_rejects_ambiguous_model_json(context, tmp_path):
    executor, runner, spec, _ = setup_executor(context, tmp_path)
    raw = b'{"metric":"excess_return","metric":"total_return"}'
    with pytest.raises(ValueError, match="JSON"):
        execute(executor, spec, raw)
    assert runner.calls == []


def test_executor_does_not_relabel_excess_return_model(context, tmp_path):
    executor, runner, spec, raw = setup_executor(context, tmp_path, model_metric="excess_return")
    with pytest.raises(ValueError, match="total_return"):
        execute(executor, spec, raw)
    assert runner.calls == []


@pytest.mark.parametrize("case", ["late_start", "late_finish", "backward_clock", "naive"])
def test_executor_rejects_invalid_actual_execution_times(context, tmp_path, case):
    available = context[4]
    before = available - timedelta(milliseconds=100)
    ticks = {
        "late_start": [available + timedelta(microseconds=1)],
        "late_finish": [before, available + timedelta(microseconds=1)],
        "backward_clock": [available, before],
        "naive": [before.replace(tzinfo=None)],
    }[case]
    executor, _, spec, raw = setup_executor(context, tmp_path, ticks=ticks)
    with pytest.raises(ValueError):
        execute(executor, spec, raw)


@pytest.mark.parametrize("output", [
    {"metric": "excess_return", "expectedValue": 0.01},
    {"metric": "total_return", "expectedValue": 0.99},
    {"metric": "total_return", "expectedValue": float("nan")},
    {"metric": "total_return", "expectedValue": True},
])
def test_executor_rejects_unusable_or_mismatched_observed_output(context, tmp_path, output):
    class InvalidRunner:
        def predict(self, **kwargs):
            return output
    executor, _, spec, raw = setup_executor(context, tmp_path, runner=InvalidRunner())
    with pytest.raises(ValueError):
        execute(executor, spec, raw)


def test_executor_rejects_runner_mutating_exact_inputs(context, tmp_path):
    class MutatingRunner:
        def predict(self, *, inputs, **kwargs):
            inputs[0]["content"].clear()
            return {"metric": "total_return", "expectedValue": 0.01}
    executor, _, spec, raw = setup_executor(context, tmp_path, runner=MutatingRunner())
    with pytest.raises(ValueError, match="modificó"):
        execute(executor, spec, raw)


def test_executor_rejects_fmp_model_identity(context, tmp_path):
    executor, runner, spec, raw = setup_executor(context, tmp_path)
    model = json.loads(raw)
    model["name"] = "Financial Modeling Prep"
    with pytest.raises(ValueError, match="FMP"):
        execute(executor, spec, json.dumps(model).encode())
    assert runner.calls == []
