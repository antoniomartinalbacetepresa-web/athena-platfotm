from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api import recommendation_athena_synthesis as api


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _cycle_record() -> dict:
    return {
        "cycle_hash": HASH_A,
        "radar_hash": HASH_B,
    }


def _contract() -> dict:
    return {
        "inputAsOf": datetime(2026, 9, 17, tzinfo=timezone.utc),
        "evidenceIds": ("investors:1",),
        "coveredCategories": ("investors",),
        "hasNews": False,
        "hasInvestors": True,
    }


def _investors_record(assessment_fingerprint: str) -> dict:
    return {
        "synthesis_hash": HASH_C,
        "radar_hash": HASH_B,
        "package": {
            "synthesis": {
                "assessments": [
                    {
                        "evidenceId": "investors:1",
                        "assessmentFingerprint": assessment_fingerprint,
                        "sourceRef": "https://example.com/investors/1",
                    }
                ]
            }
        },
    }


def _request(input_fingerprint: str) -> api.AthenaSynthesisRequest:
    return api.AthenaSynthesisRequest(
        modelProvider="test-provider",
        modelName="test-model",
        modelVersion="1",
        inputFingerprint=input_fingerprint,
        generatedAt=datetime(2026, 9, 17, 0, 1, tzinfo=timezone.utc),
        summary="Research explanation only.",
        rationale="Bound to the complete canonical input contract.",
        uncertainties=["External model execution is not independently verified."],
        evidenceIds=["investors:1"],
    )


def test_endpoint_rejects_model_output_after_investors_assessment_changes(monkeypatch) -> None:
    cycle = _cycle_record()
    contract = _contract()
    before_investors = _investors_record(HASH_D)
    after_investors = _investors_record("e" * 64)
    before = api._input_contract(cycle, None, before_investors, contract)
    after = api._input_contract(cycle, None, after_investors, contract)

    assert before["inputFingerprint"] != after["inputFingerprint"]

    monkeypatch.setattr(
        api,
        "_dependencies",
        lambda cycle_hash: (cycle, None, after_investors, contract),
    )

    build_called = False

    def _unexpected_build(**kwargs):
        nonlocal build_called
        build_called = True
        raise AssertionError("stale canonical input must be rejected before model validation")

    monkeypatch.setattr(api.athena_service, "build", _unexpected_build)

    with pytest.raises(HTTPException) as exc_info:
        api.post_athena_synthesis(HASH_A, _request(before["inputFingerprint"]))

    assert exc_info.value.status_code == 400
    assert "no coincide con News/Investors/ciclo canónicos" in exc_info.value.detail
    assert build_called is False


def test_endpoint_passes_same_verified_canonical_fingerprint_to_model_and_service(monkeypatch) -> None:
    cycle = _cycle_record()
    contract = _contract()
    investors = _investors_record(HASH_D)
    canonical = api._input_contract(cycle, None, investors, contract)["inputFingerprint"]

    monkeypatch.setattr(
        api,
        "_dependencies",
        lambda cycle_hash: (cycle, None, investors, contract),
    )

    captured: dict[str, object] = {}

    class _Result:
        def to_api_dict(self) -> dict:
            return {
                "modelProvider": "test-provider",
                "modelName": "test-model",
                "modelVersion": "1",
                "generatedAt": "2026-09-17T00:01:00+00:00",
                "summary": "Research explanation only.",
                "rationale": "Bound to the complete canonical input contract.",
                "uncertainties": ["External model execution is not independently verified."],
                "evidenceIds": ["investors:1"],
                "inputFingerprint": canonical,
                "recommendationInfluence": False,
                "automaticTrading": False,
            }

    def _build(**kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr(api.athena_service, "build", _build)
    monkeypatch.setattr(
        api.athena_repository,
        "append",
        lambda **kwargs: {
            "synthesis_hash": "f" * 64,
            "cycle_hash": HASH_A,
            "radar_hash": HASH_B,
            "news_synthesis_hash": None,
            "created_at": "2026-09-17T00:01:00+00:00",
        },
    )

    response = api.post_athena_synthesis(HASH_A, _request(canonical))

    assert captured["canonical_input_fingerprint"] == canonical
    assert captured["model_output"].input_fingerprint == canonical
    assert response["data"]["provenance"]["inputFingerprint"] == canonical
    assert response["data"]["synthesis"]["recommendationInfluence"] is False
    assert response["data"]["synthesis"]["automaticTrading"] is False
