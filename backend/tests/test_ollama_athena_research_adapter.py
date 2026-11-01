from datetime import datetime, timedelta, timezone

import pytest

from app.services.ollama_athena_research_adapter import OllamaAthenaResearchAdapter

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
CYCLE_HASH = "1" * 64
RADAR_HASH = "2" * 64
NEWS_HASH = "3" * 64


class StubClient:
    def __init__(self, output=None):
        self.calls = []
        self.output = output if output is not None else {
            "summary": "El emisor publicó una noticia.",
            "rationale": "La evidencia requiere revisión humana.",
            "uncertainties": ["Impacto económico no confirmado."],
        }

    def generate_json(self, *, prompt, required_fields):
        self.calls.append((prompt, required_fields))
        return self.output


def cycle():
    return {
        "cycle_hash": CYCLE_HASH, "radar_hash": RADAR_HASH,
        "package": {
            "cycle": {"asOf": (NOW - timedelta(days=1)).isoformat(), "integrity": {
                "cycleHash": CYCLE_HASH, "radarHash": RADAR_HASH,
            }},
            "radar": {"asOf": (NOW - timedelta(days=1)).isoformat(), "candidates": [{
                "instrumentId": "issuer:acme", "symbol": "ACME",
                "evidence": [{"evidenceId": "news-1", "category": "news",
                              "summary": "Anuncio del emisor.", "sourceRef": "https://example.org/news/1",
                              "availableAt": (NOW - timedelta(days=2)).isoformat()},
                             {"evidenceId": "risk-1", "category": "factor_risk",
                              "summary": "Riesgo de concentración."}],
            }]},
        },
    }


def news():
    return {"cycle_hash": CYCLE_HASH, "radar_hash": RADAR_HASH, "synthesis_hash": NEWS_HASH}


def adapter(client):
    return OllamaAthenaResearchAdapter(
        client=client, model_version="8f68893c685c", now_provider=lambda: NOW,
    )


def test_historical_cycle_can_be_explained_with_actual_generation_date():
    client = StubClient()
    result = adapter(client).build(cycle_record=cycle(), news_synthesis_record=news())
    assert result.evidence_ids == ("news-1", "risk-1")
    assert result.generated_at == NOW.isoformat()
    assert result.model_provider == "ollama"
    assert result.to_api_dict()["automaticTrading"] is False
    assert result.to_api_dict()["modelExecutionVerified"] is False
    assert len(client.calls) == 1


def test_missing_news_fails_before_inference():
    client = StubClient()
    with pytest.raises(ValueError, match="síntesis News"):
        adapter(client).build(cycle_record=cycle())
    assert client.calls == []


def test_wrong_news_cycle_hash_fails_before_inference():
    client = StubClient()
    wrong = dict(news(), cycle_hash="9" * 64)
    with pytest.raises(ValueError, match="Research Cycle"):
        adapter(client).build(cycle_record=cycle(), news_synthesis_record=wrong)
    assert client.calls == []


@pytest.mark.parametrize("output", [
    {"summary": "x", "rationale": "y", "uncertainties": []},
    {"summary": "x", "rationale": "y", "uncertainties": "unknown"},
    {"summary": "x", "rationale": "y", "uncertainties": ["z"], "buy": True},
    {"summary": "x", "rationale": "", "uncertainties": ["z"]},
])
def test_invalid_model_output_fails_closed(output):
    with pytest.raises(ValueError):
        adapter(StubClient(output)).build(cycle_record=cycle(), news_synthesis_record=news())


def test_duplicate_evidence_fails_before_inference():
    client = StubClient()
    bad = cycle()
    bad["package"]["radar"]["candidates"][0]["evidence"][1]["evidenceId"] = "news-1"
    with pytest.raises(ValueError, match="repetirse"):
        adapter(client).build(cycle_record=bad, news_synthesis_record=news())
    assert client.calls == []


def test_future_cycle_cutoff_fails_before_model_inference():
    client = StubClient()
    future_cycle = cycle()
    future_as_of = (NOW + timedelta(minutes=10)).isoformat()
    future_cycle["package"]["cycle"]["asOf"] = future_as_of
    future_cycle["package"]["radar"]["asOf"] = future_as_of
    with pytest.raises(ValueError, match="antes del inputAsOf"):
        adapter(client).build(cycle_record=future_cycle, news_synthesis_record=news())
    assert client.calls == []


def test_clock_rollback_during_inference_fails_closed():
    client = StubClient()
    readings = iter((NOW, NOW - timedelta(seconds=1)))
    runner = OllamaAthenaResearchAdapter(
        client=client, model_version="8f68893c685c",
        now_provider=lambda: next(readings),
    )
    with pytest.raises(ValueError, match="reloj retrocedió"):
        runner.build(cycle_record=cycle(), news_synthesis_record=news())
    assert len(client.calls) == 1


def test_naive_generation_clock_fails_before_inference():
    client = StubClient()
    runner = OllamaAthenaResearchAdapter(
        client=client, model_version="8f68893c685c",
        now_provider=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(ValueError, match="timezone"):
        runner.build(cycle_record=cycle(), news_synthesis_record=news())
    assert client.calls == []
