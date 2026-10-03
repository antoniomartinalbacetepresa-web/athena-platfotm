from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_athena_synthesis_service import (
    AthenaSynthesisModelInput,
    RecommendationAthenaSynthesisService,
)


CYCLE_HASH = "a" * 64
RADAR_HASH = "b" * 64
BASE_AS_OF = "2026-09-17T00:00:00+00:00"
CANONICAL_A = "c" * 64
CANONICAL_B = "d" * 64


def _cycle_record() -> dict:
    return {
        "cycle_hash": CYCLE_HASH,
        "radar_hash": RADAR_HASH,
        "package": {
            "cycle": {
                "asOf": BASE_AS_OF,
                "integrity": {
                    "cycleHash": CYCLE_HASH,
                    "radarHash": RADAR_HASH,
                },
            },
            "radar": {
                "asOf": BASE_AS_OF,
                "candidates": [
                    {
                        "instrumentId": "instrument-1",
                        "symbol": "TEST",
                        "evidence": [
                            {
                                "evidenceId": "investors:1",
                                "category": "investors",
                            }
                        ],
                    }
                ],
            },
        },
    }


def _model(fingerprint: str) -> AthenaSynthesisModelInput:
    return AthenaSynthesisModelInput(
        model_provider="test-provider",
        model_name="test-model",
        model_version="1",
        input_fingerprint=fingerprint,
        generated_at=datetime(2026, 9, 17, 0, 1, tzinfo=timezone.utc),
        summary="Research explanation only.",
        rationale="Bound to the complete canonical input contract.",
        uncertainties=("External model execution is not independently verified.",),
        evidence_ids=("investors:1",),
    )


def test_model_validation_accepts_complete_canonical_fingerprint() -> None:
    service = RecommendationAthenaSynthesisService()

    result = service.build(
        cycle_record=_cycle_record(),
        news_synthesis_record=None,
        canonical_input_fingerprint=CANONICAL_A,
        model_output=_model(CANONICAL_A),
    )

    assert result.input_fingerprint == CANONICAL_A
    assert result.to_api_dict()["recommendationInfluence"] is False
    assert result.to_api_dict()["automaticTrading"] is False


def test_model_output_from_previous_canonical_contract_is_rejected() -> None:
    service = RecommendationAthenaSynthesisService()

    with pytest.raises(ValueError, match="input_fingerprint no coincide con los artefactos canónicos"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=None,
            canonical_input_fingerprint=CANONICAL_B,
            model_output=_model(CANONICAL_A),
        )


def test_legacy_direct_service_validation_still_uses_verified_base_artifacts() -> None:
    service = RecommendationAthenaSynthesisService()
    base = service.input_fingerprint(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=None,
        input_as_of=datetime.fromisoformat(BASE_AS_OF),
        evidence_ids=("investors:1",),
        covered_categories=("investors",),
    )

    result = service.build(
        cycle_record=_cycle_record(),
        news_synthesis_record=None,
        model_output=_model(base),
    )

    assert result.input_fingerprint == base
