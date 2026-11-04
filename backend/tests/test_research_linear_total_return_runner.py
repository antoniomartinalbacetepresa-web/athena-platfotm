"""Synthetic arithmetic contracts, not trained models or production evidence."""
import json

import pytest

from app.services.research_linear_total_return_runner import ResearchLinearTotalReturnRunner
from test_recommendation_research_model_executor import context, setup_executor


def contract():
    return {
        "runnerVersion": "research-linear-total-return-v1", "name": "test-only",
        "version": "fixture", "metric": "total_return", "horizonSeconds": 86400,
        "intercept": 0.01,
        "features": [{"sourceRef": "persisted:test", "path": ["artifact", "value"],
                      "offset": 100, "scale": 10, "coefficient": 0.02}],
    }


def predict(model, inputs=None):
    return ResearchLinearTotalReturnRunner().predict(
        model_bytes=json.dumps(model).encode(),
        inputs=inputs if inputs is not None else [
            {"evidence": {"sourceRef": "persisted:test"}, "content": {"artifact": {"value": 110}}}
        ],
    )


def test_explicit_transform_and_inference_do_not_mutate_artifact():
    model = contract()
    original = json.dumps(model)
    assert predict(model) == {"metric": "total_return", "expectedValue": 0.03}
    assert json.dumps(model) == original


@pytest.mark.parametrize("field,value", [("scale", 0), ("scale", -1),
                                         ("coefficient", True), ("offset", float("nan")),
                                         ("path", ["missing"]), ("sourceRef", "foreign")])
def test_invalid_feature_fails_closed(field, value):
    model = contract()
    model["features"][0][field] = value
    with pytest.raises(ValueError):
        predict(model)


def test_duplicate_features_rejected():
    model = contract()
    model["features"].append(dict(model["features"][0]))
    with pytest.raises(ValueError):
        predict(model)


def test_unused_input_rejected():
    inputs = [{"evidence": {"sourceRef": ref}, "content": {"artifact": {"value": 110}}}
              for ref in ("persisted:test", "unused")]
    with pytest.raises(ValueError):
        predict(contract(), inputs)


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match="Duplicated JSON"):
        ResearchLinearTotalReturnRunner().predict(model_bytes=b'{"metric":1,"metric":2}', inputs=[])


def test_excess_return_not_relabelled():
    model = contract()
    model["metric"] = "expectedExcessReturn"
    with pytest.raises(ValueError):
        predict(model)


def test_concrete_runner_generates_and_persists_observed_receipt(context, tmp_path):
    import hashlib
    from app.services.recommendation_research_executed_forecast_store_service import RecommendationResearchExecutedForecastStoreService
    executor, _, template, _ = setup_executor(context, tmp_path, runner=ResearchLinearTotalReturnRunner())
    snapshot = executor._manifest.materialize_specification(template)
    model = contract()
    model["features"] = [
        {"sourceRef": item["evidence"]["sourceRef"],
         "path": ["artifact", "value"] if "artifact" in item["content"] else ["close"],
         "offset": 0, "scale": 1, "coefficient": 0.0001}
        for item in snapshot["inputs"]
    ]
    raw = json.dumps(model).encode()
    store = RecommendationResearchExecutedForecastStoreService(
        database=context[0], executor=executor, now_provider=lambda: context[4])
    result = store.generate_and_persist(specification_template=template, model_bytes=raw,
                                       pinned_artifact_hash=hashlib.sha256(raw).hexdigest())
    receipt = result["receipt"]["artifact"]
    assert receipt["artifactVersion"] == "research-model-execution-receipt-v2"
    assert receipt["output"]["expectedValue"] == result["specification"]["artifact"]["expectedValue"]
    assert result["productionLearningEligible"] is False
