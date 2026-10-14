from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_athena_synthesis_service import (
    AthenaSynthesisModelInput,
    RecommendationAthenaSynthesisService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
CYCLE_HASH = "1" * 64
RADAR_HASH = "2" * 64
NEWS_HASH = "3" * 64


def _cycle_record() -> dict[str, object]:
    return {
        "cycle_hash": CYCLE_HASH,
        "radar_hash": RADAR_HASH,
        "package": {
            "cycle": {
                "asOf": AS_OF.isoformat(),
                "integrity": {
                    "cycleHash": CYCLE_HASH,
                    "radarHash": RADAR_HASH,
                },
            },
            "radar": {
                "asOf": AS_OF.isoformat(),
                "candidates": [
                    {
                        "instrumentId": "instrument-aapl",
                        "symbol": "AAPL",
                        "evidence": [
                            {
                                "evidenceId": "news-1",
                                "category": "news",
                            },
                            {
                                "evidenceId": "risk-1",
                                "category": "factor_risk",
                            },
                        ],
                    }
                ],
            },
        },
    }


def _news_record() -> dict[str, object]:
    return {
        "cycle_hash": CYCLE_HASH,
        "radar_hash": RADAR_HASH,
        "synthesis_hash": NEWS_HASH,
    }


def _model_input(service: RecommendationAthenaSynthesisService, **overrides: object):
    fingerprint = service.input_fingerprint(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        input_as_of=AS_OF,
        evidence_ids=("news-1", "risk-1"),
        covered_categories=("news", "factor_risk"),
    )
    values: dict[str, object] = {
        "model_provider": "external-model-provider",
        "model_name": "athena-research-synthesis",
        "model_version": "2026-01",
        "input_fingerprint": fingerprint,
        "generated_at": AS_OF + timedelta(minutes=1),
        "summary": "Material news and factor-risk evidence require human review.",
        "rationale": "The synthesis explains the frozen evidence without assigning investment probability.",
        "uncertainties": ("The operating impact remains uncertain.",),
        "evidence_ids": ("news-1", "risk-1"),
    }
    values.update(overrides)
    return AthenaSynthesisModelInput(**values)


def test_athena_synthesis_binds_cycle_news_and_complete_evidence() -> None:
    service = RecommendationAthenaSynthesisService()
    result = service.build(
        cycle_record=_cycle_record(),
        news_synthesis_record=_news_record(),
        model_output=_model_input(service),
    ).to_api_dict()

    assert result["status"] == "validated_external_athena_synthesis"
    assert result["mode"] == "research_explanation_only"
    assert result["cycleHash"] == CYCLE_HASH
    assert result["radarHash"] == RADAR_HASH
    assert result["newsSynthesisHash"] == NEWS_HASH
    assert result["evidenceIds"] == ["news-1", "risk-1"]
    assert result["coveredCategories"] == ["factor_risk", "news"]
    assert result["uncertainties"]
    assert result["modelExecutionVerified"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["recommendationInfluence"] is False
    assert result["automaticScoring"] is False
    assert result["automaticTrading"] is False
    assert result["automaticProductionPromotion"] is False
    assert len(result["inputFingerprint"]) == 64
    assert len(result["outputFingerprint"]) == 64


def test_athena_synthesis_requires_news_artifact_when_cycle_contains_news() -> None:
    service = RecommendationAthenaSynthesisService()
    with pytest.raises(ValueError, match="requiere su síntesis News canónica"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=None,
            model_output=_model_input(service),
        )


def test_athena_synthesis_rejects_silent_evidence_omission() -> None:
    service = RecommendationAthenaSynthesisService()
    model = _model_input(service, evidence_ids=("news-1",))
    with pytest.raises(ValueError, match="exactamente toda la evidencia Radar"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=_news_record(),
            model_output=model,
        )


def test_athena_synthesis_rejects_wrong_input_fingerprint() -> None:
    service = RecommendationAthenaSynthesisService()
    model = _model_input(service, input_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="input_fingerprint"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=_news_record(),
            model_output=model,
        )


def test_athena_synthesis_requires_declared_uncertainty() -> None:
    service = RecommendationAthenaSynthesisService()
    model = _model_input(service, uncertainties=())
    with pytest.raises(ValueError, match="al menos una incertidumbre"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=_news_record(),
            model_output=model,
        )


def test_athena_synthesis_rejects_output_generated_before_frozen_cycle() -> None:
    service = RecommendationAthenaSynthesisService()
    model = _model_input(service, generated_at=AS_OF - timedelta(seconds=1))
    with pytest.raises(ValueError, match="no puede preceder"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=_news_record(),
            model_output=model,
        )


def test_athena_synthesis_rejects_fmp_model_provider() -> None:
    service = RecommendationAthenaSynthesisService()
    model = _model_input(service, model_provider="Financial Modeling Prep")
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        service.build(
            cycle_record=_cycle_record(),
            news_synthesis_record=_news_record(),
            model_output=model,
        )
