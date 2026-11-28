from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_news_synthesis as news_api
import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.repositories.recommendation_news_synthesis_repository import (
    RecommendationNewsSynthesisRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.services.recommendation_news_synthesis_service import (
    RecommendationNewsSynthesisService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
PUBLISHED_AT = AVAILABLE_AT - timedelta(minutes=20)
GENERATED_AT = AVAILABLE_AT + timedelta(minutes=10)


def _cycle_payload() -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl-news",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "radarEvidence": [
            {
                "evidenceId": "news-evidence-1",
                "category": "news",
                "urgency": "material",
                "summary": "Issuer announces a material operating update.",
                "availableAt": AVAILABLE_AT.isoformat(),
                "source": "news",
                "sourceRef": "https://example.com/news/aapl-operating-update",
                "provider": "google_news_rss",
                "publisher": "Example Financial News",
                "publishedAt": PUBLISHED_AT.isoformat(),
            }
        ],
        "journalId": "journal-aapl-news",
        "revisionId": "revision-1",
        "recordedAt": AVAILABLE_AT.isoformat(),
        "thesis": "Frozen research thesis before subsequent outcome evidence.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-news-1",
                "kind": "assumption",
                "availableAt": (AVAILABLE_AT - timedelta(minutes=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:journal:news:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-news-1",
                "kind": "alternative_explanation",
                "claim": "The operating update may have a temporary explanation.",
                "strength": "material",
                "availableAt": AVAILABLE_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:news:1",
            }
        ],
    }


def _repositories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = AthenaDatabase(tmp_path / "news-cycle.db")
    journal_repository = RecommendationInvestmentJournalRepository(database)
    cycle_repository = RecommendationProfessionalResearchCycleRepository(database)
    synthesis_repository = RecommendationNewsSynthesisRepository(database)

    monkeypatch.setattr(cycle_api, "journal_repository", journal_repository)
    monkeypatch.setattr(cycle_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(news_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(news_api, "synthesis_repository", synthesis_repository)
    return cycle_repository, synthesis_repository


def _create_cycle_and_assessment(
    client: TestClient,
    cycle_repository: RecommendationProfessionalResearchCycleRepository,
) -> tuple[str, str, dict[str, object]]:
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_cycle_payload(),
    )
    assert response.status_code == 200, response.text
    cycle = response.json()["data"]
    cycle_hash = cycle["integrity"]["cycleHash"]
    record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    radar = news_api._radar_from_cycle_record(record)
    evidence = radar.candidates[0].evidence[0]
    fingerprint = RecommendationNewsSynthesisService().evidence_fingerprint(
        instrument_id=radar.candidates[0].instrument_id,
        symbol=radar.candidates[0].symbol,
        evidence=evidence,
    )
    assessment = {
        "evidenceId": evidence.evidence_id,
        "modelProvider": "external_model_provider",
        "modelName": "news-research-model",
        "modelVersion": "2026-01",
        "inputFingerprint": fingerprint,
        "generatedAt": GENERATED_AT.isoformat(),
        "summary": "The update is material research context and requires human review.",
        "importance": "high",
        "impactDirection": "positive",
        "impactMagnitude": 0.7,
        "confidence": 0.8,
    }
    return cycle_hash, record["radar_hash"], assessment


def test_news_synthesis_is_bound_to_persisted_cycle_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, synthesis_repository = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash, radar_hash, assessment = _create_cycle_and_assessment(
        client, cycle_repository
    )

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={"minimumImportance": "medium", "assessments": [assessment]},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["cycleBindingVerified"] is True
    assert data["cycleHash"] == cycle_hash
    assert data["radarHash"] == radar_hash
    assert data["synthesis"]["status"] == "validated_external_model_output"
    assert data["synthesis"]["assessedCount"] == 1
    assert data["synthesis"]["includedCount"] == 1
    assert data["synthesis"]["items"][0]["evidenceId"] == "news-evidence-1"
    assert data["synthesis"]["items"][0]["evidenceProvider"] == "google_news_rss"
    assert data["synthesis"]["items"][0]["publisher"] == "Example Financial News"
    assert data["synthesis"]["modelExecutionVerified"] is False
    assert data["synthesis"]["productionTruthClaimed"] is False
    assert data["synthesis"]["recommendationInfluence"] is False
    assert data["recommendationInfluence"] is False
    assert data["automaticScoring"] is False
    assert data["automaticTrading"] is False
    assert data["persistence"]["appendOnly"] is True
    assert data["persistence"]["packageIntegrityVerified"] is True
    assert len(data["persistence"]["synthesisHash"]) == 64

    persisted = synthesis_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
    assert persisted["radar_hash"] == radar_hash

    read = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis"
    )
    assert read.status_code == 200, read.text
    read_data = read.json()["data"]
    assert read_data["cycleHash"] == cycle_hash
    assert read_data["radarHash"] == radar_hash
    assert read_data["synthesis"] == data["synthesis"]
    assert read_data["persistence"]["synthesisHash"] == data["persistence"]["synthesisHash"]


def test_news_synthesis_rejects_wrong_cycle_evidence_fingerprint_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, synthesis_repository = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash, _, assessment = _create_cycle_and_assessment(client, cycle_repository)
    assessment["inputFingerprint"] = "0" * 64

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={"minimumImportance": "low", "assessments": [assessment]},
    )

    assert response.status_code == 400
    assert "input_fingerprint" in response.json()["detail"]
    with pytest.raises(ValueError, match="no tiene síntesis News"):
        synthesis_repository.get_by_cycle_hash(cycle_hash=cycle_hash)


def test_news_synthesis_rejects_model_output_before_pit_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, synthesis_repository = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash, _, assessment = _create_cycle_and_assessment(client, cycle_repository)
    assessment["generatedAt"] = (AVAILABLE_AT - timedelta(seconds=1)).isoformat()

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={"minimumImportance": "low", "assessments": [assessment]},
    )

    assert response.status_code == 400
    assert "disponibilidad PIT" in response.json()["detail"]
    with pytest.raises(ValueError, match="no tiene síntesis News"):
        synthesis_repository.get_by_cycle_hash(cycle_hash=cycle_hash)


def test_news_synthesis_prevents_retrospective_model_shopping_for_same_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, _ = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash, _, assessment = _create_cycle_and_assessment(client, cycle_repository)

    first = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={"minimumImportance": "low", "assessments": [assessment]},
    )
    assert first.status_code == 200, first.text

    changed = dict(assessment)
    changed["summary"] = "A different retrospective interpretation must not replace the first output."
    second = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={"minimumImportance": "low", "assessments": [changed]},
    )

    assert second.status_code == 400
    assert "selección retrospectiva" in second.json()["detail"]


def test_news_synthesis_cycle_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    path = "/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis"
    assert path in paths
    assert "post" in paths[path]
    assert "get" in paths[path]
