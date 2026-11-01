"""Manual end-to-end local Ollama smoke test with SYNTHETIC research records.

Usage (from backend):
    .\\.venv\\Scripts\\python.exe scripts/smoke_ollama_research_pipeline.py

No database writes, network news fetch, investment orders or production promotion.
The cycle/news hashes below are synthetic test fixtures, NOT persisted evidence.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Allow direct execution from backend/scripts without PYTHONPATH configuration.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ollama_athena_research_adapter import OllamaAthenaResearchAdapter
from app.services.ollama_news_research_adapter import OllamaNewsResearchAdapter
from app.services.ollama_research_synthesis_client import OllamaResearchSynthesisClient
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def run() -> dict[str, object]:
    # News uses a forward cutoff to permit real inference; ATHENA then
    # explains that frozen cycle only after the cutoff has elapsed.
    now = datetime.now(timezone.utc)
    as_of = now + timedelta(minutes=10)
    available_at = now - timedelta(minutes=10)
    evidence = AthenaRadarEvidenceInput(
        evidence_id="synthetic-news-1",
        category="news",
        urgency="material",
        summary="EJEMPLO HIPOTÉTICO: una empresa comunica crecimiento de ingresos del 8%; no aporta márgenes ni flujo de caja.",
        available_at=available_at,
        source="news",
        source_ref="https://example.org/synthetic-news/1",
        provider="synthetic_fixture",
        publisher="Synthetic Example",
        published_at=available_at - timedelta(minutes=1),
    )
    radar = RecommendationAthenaRadarService().build(
        as_of=as_of,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="synthetic:issuer", symbol="DEMO",
                evidence=(evidence,),
            ),
        ),
    )
    client = OllamaResearchSynthesisClient()
    news = OllamaNewsResearchAdapter(
        client=client, model_version="local-qwen3-1.7b",
    ).build(radar_result=radar)
    news_api = news.to_api_dict()

    # Synthetic package only: this is not a database round trip or a
    # cryptographically verified persisted Research Cycle.
    radar_api = radar.to_api_dict()
    cycle_hash = _digest({"fixture": "synthetic-cycle", "asOf": radar.as_of})
    radar_hash = _digest(radar_api)
    cycle_record = {
        "cycle_hash": cycle_hash,
        "radar_hash": radar_hash,
        "package": {
            "cycle": {
                "asOf": radar.as_of,
                "integrity": {"cycleHash": cycle_hash, "radarHash": radar_hash},
            },
            "radar": radar_api,
        },
    }
    news_record = {
        "cycle_hash": cycle_hash,
        "radar_hash": radar_hash,
        "synthesis_hash": _digest(news_api),
    }
    # The historical model contract forbids ATHENA generation before inputAsOf.
    # Do not sleep for ten minutes: inject a deterministic, future generation
    # clock ONLY for this synthetic smoke fixture (not a production timestamp).
    synthetic_generation_clock = lambda: as_of + timedelta(seconds=1)
    athena = OllamaAthenaResearchAdapter(
        client=client, model_version="local-qwen3-1.7b",
        now_provider=synthetic_generation_clock,
    ).build(cycle_record=cycle_record, news_synthesis_record=news_record)
    athena_api = athena.to_api_dict()

    assert news.assessed_count == 1
    assert athena.evidence_ids == ("synthetic-news-1",)
    assert news_api["automaticTrading"] is False
    assert athena_api["automaticTrading"] is False
    assert athena_api["productionEligible"] is False
    assert athena_api["modelExecutionVerified"] is False
    return {
        "status": "local_synthetic_e2e_passed",
        "realModelCalls": 2,
        "fixtureType": "synthetic_not_persisted",
        "athenaGenerationTime": "synthetic_clock_not_actual_execution_time",
        "news": news_api,
        "athena": athena_api,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
