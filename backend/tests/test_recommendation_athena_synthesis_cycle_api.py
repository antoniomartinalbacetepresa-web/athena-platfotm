from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_athena_synthesis as athena_api
import app.api.recommendation_news_synthesis as news_api
import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_athena_synthesis_repository import (
    RecommendationAthenaSynthesisRepository,
)
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
NEWS_GENERATED_AT = AVAILABLE_AT + timedelta(minutes=10)
ATHENA_GENERATED_AT = AS_OF + timedelta(minutes=1)


def _cycle_payload() -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl-athena",
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
        "journalId": "journal-aapl-athena",
        "revisionId": "revision-1",
        "recordedAt": AVAILABLE_AT.isoformat(),
        "thesis": "Frozen research thesis before later outcomes.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-athena-1",
                "kind": "assumption",
                "availableAt": (AVAILABLE_AT - timedelta(minutes=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:journal:athena:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-athena-1",
                "kind": "alternative_explanation",
                "claim": "The operating update may have a temporary explanation.",
                "strength": "material",
                "availableAt": AVAILABLE_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:athena:1",
            }
        ],
    }


def _repositories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = AthenaDatabase(tmp_path / "athena-cycle-api.db")
    journal_repository = RecommendationInvestmentJournalRepository(database)
    cycle_repository = RecommendationProfessionalResearchCycleRepository(database)
    news_repository = RecommendationNewsSynthesisRepository(database)
    athena_repository = RecommendationAthenaSynthesisRepository(database)

    monkeypatch.setattr(cycle_api, "journal_repository", journal_repository)
    monkeypatch.setattr(cycle_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(news_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(news_api, "synthesis_repository", news_repository)
    monkeypatch.setattr(athena_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(athena_api, "news_repository", news_repository)
    monkeypatch.setattr(athena_api, "athena_repository", athena_repository)
    return cycle_repository, news_repository, athena_repository


def _create_cycle(client: TestClient) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_cycle_payload(),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["integrity"]["cycleHash"]


def _persist_news_synthesis(
    client: TestClient,
    cycle_repository: RecommendationProfessionalResearchCycleRepository,
    cycle_hash: str,
) -> dict[str, object]:
    record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    radar = news_api._radar_from_cycle_record(record)
    evidence = radar.candidates[0].evidence[0]
    fingerprint = RecommendationNewsSynthesisService().evidence_fingerprint(
        instrument_id=radar.candidates[0].instrument_id,
        symbol=radar.candidates[0].symbol,
        evidence=evidence,
    )
    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/news-synthesis",
        json={
            "minimumImportance": "medium",
            "assessments": [
                {
                    "evidenceId": evidence.evidence_id,
                    "modelProvider": "external_model_provider",
                    "modelName": "news-research-model",
                    "modelVersion": "2026-01",
                    "inputFingerprint": fingerprint,
                    "generatedAt": NEWS_GENERATED_AT.isoformat(),
                    "summary": "The update is material context requiring human review.",
                    "importance": "high",
                    "impactDirection": "positive",
                    "impactMagnitude": 0.7,
                    "confidence": 0.8,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _athena_request(contract: dict[str, object], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "modelProvider": "external_model_provider",
        "modelName": "athena-research-synthesis",
        "modelVersion": "2026-01",
        "inputFingerprint": contract["inputFingerprint"],
        "generatedAt": ATHENA_GENERATED_AT.isoformat(),
        "summary": "ATHENA explains the complete frozen evidence set for human review.",
        "rationale": "The narrative is bound to every Radar evidence item and the canonical News synthesis.",
        "uncertainties": ["The eventual operating and market response remains uncertain."],
        "evidenceIds": contract["evidenceIds"],
    }
    payload.update(overrides)
    return payload


def test_athena_synthesis_requires_news_synthesis_for_news_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)

    contract = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    )
    assert contract.status_code == 404
    assert "no tiene síntesis News" in contract.json()["detail"]


def test_athena_synthesis_full_cycle_is_bound_persisted_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, news_repository, athena_repository = _repositories(
        tmp_path, monkeypatch
    )
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    news_data = _persist_news_synthesis(client, cycle_repository, cycle_hash)

    contract_response = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    )
    assert contract_response.status_code == 200, contract_response.text
    contract = contract_response.json()["data"]
    cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    news_record = news_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
    assert contract["cycleHash"] == cycle_hash
    assert contract["radarHash"] == cycle_record["radar_hash"]
    assert contract["newsSynthesisHash"] == news_record["synthesis_hash"]
    assert contract["newsSynthesisHash"] == news_data["persistence"]["synthesisHash"]
    assert contract["evidenceIds"] == ["news-evidence-1"]
    assert contract["coveredCategories"] == ["news"]
    assert len(contract["inputFingerprint"]) == 64
    assert contract["requiredCoverage"] == "all_cycle_radar_evidence"
    assert contract["advisoryStatus"] == "no_advice"
    assert contract["recommendationInfluence"] is False
    assert contract["automaticTrading"] is False

    post = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json=_athena_request(contract),
    )
    assert post.status_code == 200, post.text
    data = post.json()["data"]
    synthesis = data["synthesis"]
    assert data["artifactBindingVerified"] is True
    assert synthesis["status"] == "validated_external_athena_synthesis"
    assert synthesis["mode"] == "research_explanation_only"
    assert synthesis["cycleHash"] == cycle_hash
    assert synthesis["radarHash"] == cycle_record["radar_hash"]
    assert synthesis["newsSynthesisHash"] == news_record["synthesis_hash"]
    assert synthesis["evidenceIds"] == ["news-evidence-1"]
    assert synthesis["uncertainties"]
    assert synthesis["modelExecutionVerified"] is False
    assert synthesis["advisoryStatus"] == "no_advice"
    assert synthesis["productionEligible"] is False
    assert synthesis["recommendationInfluence"] is False
    assert synthesis["automaticScoring"] is False
    assert synthesis["automaticTrading"] is False
    assert synthesis["automaticProductionPromotion"] is False
    assert data["persistence"]["appendOnly"] is True
    assert data["persistence"]["packageIntegrityVerified"] is True
    assert len(data["persistence"]["synthesisHash"]) == 64

    persisted = athena_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
    assert persisted["synthesis_hash"] == data["persistence"]["synthesisHash"]

    read = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis"
    )
    assert read.status_code == 200, read.text
    assert read.json()["data"]["synthesis"] == synthesis
    assert (
        read.json()["data"]["persistence"]["synthesisHash"]
        == data["persistence"]["synthesisHash"]
    )


def test_athena_synthesis_rejects_wrong_input_fingerprint_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, _, athena_repository = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    _persist_news_synthesis(client, cycle_repository, cycle_hash)
    contract = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    ).json()["data"]

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json=_athena_request(contract, inputFingerprint="0" * 64),
    )
    assert response.status_code == 400
    assert "input_fingerprint" in response.json()["detail"]
    with pytest.raises(ValueError, match="no tiene ATHENA synthesis"):
        athena_repository.get_by_cycle_hash(cycle_hash=cycle_hash)


def test_athena_synthesis_rejects_silent_evidence_omission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, _, athena_repository = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    _persist_news_synthesis(client, cycle_repository, cycle_hash)
    contract = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    ).json()["data"]

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json=_athena_request(contract, evidenceIds=["fabricated-evidence"]),
    )
    assert response.status_code == 400
    assert "exactamente toda la evidencia Radar" in response.json()["detail"]
    with pytest.raises(ValueError, match="no tiene ATHENA synthesis"):
        athena_repository.get_by_cycle_hash(cycle_hash=cycle_hash)


def test_athena_synthesis_prevents_retrospective_narrative_shopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_repository, _, _ = _repositories(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    _persist_news_synthesis(client, cycle_repository, cycle_hash)
    contract = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    ).json()["data"]

    first = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json=_athena_request(contract),
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json=_athena_request(
            contract,
            summary="A different retrospective narrative must not replace the first canonical synthesis.",
        ),
    )
    assert second.status_code == 400
    assert "selección retrospectiva" in second.json()["detail"]


def test_athena_synthesis_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    base = "/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis"
    assert base in paths
    assert "post" in paths[base]
    assert "get" in paths[base]
    assert f"{base}/input-contract" in paths
    assert "get" in paths[f"{base}/input-contract"]
