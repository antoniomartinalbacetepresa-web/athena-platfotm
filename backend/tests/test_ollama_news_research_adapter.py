from datetime import datetime, timedelta, timezone

import pytest

from app.services.ollama_news_research_adapter import OllamaNewsResearchAdapter
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput, AthenaRadarEvidenceInput, RecommendationAthenaRadarService,
)


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


class StubClient:
    def __init__(self, output=None):
        self.calls = []
        self.output = output or {
            "summary": "Cambio operativo descrito por el emisor.",
            "importance": "medium",
            "impactDirection": "uncertain",
            "impactMagnitude": 0.2,
            "confidence": 0.3,
        }

    def generate_json(self, *, prompt, required_fields):
        self.calls.append((prompt, required_fields))
        return self.output


def radar(*, as_of=NOW + timedelta(minutes=1), available_at=NOW - timedelta(minutes=2)):
    return RecommendationAthenaRadarService().build(
        as_of=as_of,
        candidates=(AthenaRadarCandidateInput(
            instrument_id="issuer:acme", symbol="ACME",
            evidence=(AthenaRadarEvidenceInput(
                evidence_id="news-1", category="news", urgency="material",
                summary="El emisor anuncia un cambio operativo.",
                available_at=available_at, source="news",
                source_ref="https://example.org/news/1",
                provider="google_news_rss", publisher="Example Journal",
                published_at=available_at - timedelta(minutes=1),
            ),),
        ),),
    )


def adapter(client, *, clock=lambda: NOW):
    return OllamaNewsResearchAdapter(client=client, model_version="8f68893c685c", now_provider=clock)


def test_generates_validated_non_advisory_news_draft():
    client = StubClient()
    result = adapter(client).build(radar_result=radar())
    assert result.assessed_count == 1
    assert result.assessments[0].model_provider == "ollama"
    assert result.assessments[0].input_fingerprint
    assert result.to_api_dict()["automaticTrading"] is False
    assert result.to_api_dict()["modelExecutionVerified"] is False
    assert len(client.calls) == 1


def test_historical_cycle_rejected_before_model_call():
    client = StubClient()
    with pytest.raises(ValueError, match="histórico"):
        adapter(client).build(radar_result=radar(as_of=NOW - timedelta(minutes=1), available_at=NOW - timedelta(minutes=3)))
    assert client.calls == []


@pytest.mark.parametrize("invalid", [
    {"summary": "x", "importance": "high", "impactDirection": "neutral", "impactMagnitude": 0.1, "confidence": True},
    {"summary": "x", "importance": "high", "impactDirection": "neutral", "impactMagnitude": 1.1, "confidence": 0.3},
    {"summary": "x", "importance": "buy", "impactDirection": "neutral", "impactMagnitude": 0.1, "confidence": 0.3},
    {"summary": "x", "importance": "high", "impactDirection": "neutral", "impactMagnitude": 0.1, "confidence": 0.3, "extra": 1},
])
def test_rejects_bad_model_output(invalid):
    with pytest.raises(ValueError):
        adapter(StubClient(invalid)).build(radar_result=radar())


def test_rejects_inference_finishing_after_cutoff():
    client = StubClient()
    times = iter([NOW, NOW, NOW + timedelta(minutes=2)])
    with pytest.raises(ValueError, match="intervalo PIT"):
        adapter(client, clock=lambda: next(times)).build(radar_result=radar())
    assert len(client.calls) == 1
