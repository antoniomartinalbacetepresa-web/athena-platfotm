from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_athena_synthesis as athena_api
import app.api.recommendation_investors_synthesis as investors_api
import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_investors_synthesis_repository import RecommendationInvestorsSynthesisRepository
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_investors_synthesis_service import RecommendationInvestorsSynthesisService


AS_OF = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
PUBLISHED_AT = AVAILABLE_AT - timedelta(minutes=30)


def _cycle_payload() -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl-investors",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "radarEvidence": [
            {
                "evidenceId": "a" * 64,
                "category": "investors",
                "urgency": "material",
                "summary": "Issuer filed a material quarterly report.",
                "availableAt": AVAILABLE_AT.isoformat(),
                "source": "SEC",
                "sourceRef": "https://www.sec.gov/Archives/example-10q.htm",
                "provider": "sec_edgar",
                "publisher": "SEC",
                "publishedAt": PUBLISHED_AT.isoformat(),
            }
        ],
        "journalId": "journal-aapl-investors",
        "revisionId": "revision-1",
        "recordedAt": AVAILABLE_AT.isoformat(),
        "thesis": "Frozen thesis before the filing assessment.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-investors-1",
                "kind": "assumption",
                "availableAt": (AVAILABLE_AT - timedelta(minutes=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:journal:investors:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-investors-1",
                "kind": "alternative_explanation",
                "claim": "The filing may contain temporary effects.",
                "strength": "material",
                "availableAt": AVAILABLE_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:investors:1",
            }
        ],
    }


def _wire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = AthenaDatabase(tmp_path / "athena-investors-synthesis.db")
    journal_repository = RecommendationInvestmentJournalRepository(database)
    cycle_repository = RecommendationProfessionalResearchCycleRepository(database)
    investors_repository = RecommendationInvestorsSynthesisRepository(database)
    news_repository = RecommendationNewsSynthesisRepository(database)
    athena_repository = RecommendationAthenaSynthesisRepository(database)
    monkeypatch.setattr(cycle_api, "journal_repository", journal_repository)
    monkeypatch.setattr(cycle_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(investors_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(investors_api, "synthesis_repository", investors_repository)
    monkeypatch.setattr(athena_api, "cycle_repository", cycle_repository)
    monkeypatch.setattr(athena_api, "investors_repository", investors_repository)
    monkeypatch.setattr(athena_api, "news_repository", news_repository)
    monkeypatch.setattr(athena_api, "athena_repository", athena_repository)
    return cycle_repository


def _create_cycle(client: TestClient) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_cycle_payload(),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["integrity"]["cycleHash"]


def _persist_investors(client: TestClient, cycle_repository, cycle_hash: str, *, provider: str = "external_model_provider"):
    record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    radar = investors_api._radar_from_cycle_record(record)
    evidence = radar.candidates[0].evidence[0]
    fingerprint = RecommendationInvestorsSynthesisService().evidence_fingerprint(
        instrument_id=radar.candidates[0].instrument_id,
        symbol=radar.candidates[0].symbol,
        evidence=evidence,
    )
    return client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/investors-synthesis",
        json={
            "assessments": [
                {
                    "evidenceId": evidence.evidence_id,
                    "modelProvider": provider,
                    "modelName": "investors-research-model",
                    "modelVersion": "2026-02",
                    "inputFingerprint": fingerprint,
                    "generatedAt": (AVAILABLE_AT + timedelta(minutes=10)).isoformat(),
                    "summary": "The filing is material context requiring human review.",
                    "importance": "high",
                    "impactDirection": "mixed",
                    "impactMagnitude": 0.6,
                    "confidence": 0.75,
                }
            ]
        },
    )


def test_athena_contract_fails_closed_until_investors_synthesis_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cycle_repository = _wire(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)

    missing = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    )
    assert missing.status_code == 404
    assert "Investors synthesis" in missing.json()["detail"]

    persisted = _persist_investors(client, cycle_repository, cycle_hash)
    assert persisted.status_code == 200, persisted.text
    investors_hash = persisted.json()["data"]["persistence"]["synthesisHash"]

    contract = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    )
    assert contract.status_code == 200, contract.text
    data = contract.json()["data"]
    assert data["investorsSynthesisHash"] == investors_hash
    assert data["coveredCategories"] == ["investors"]
    assert data["requiredCoverage"] == "all_cycle_radar_evidence_and_required_canonical_category_syntheses"


def test_full_investors_to_athena_cycle_binds_hash_and_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cycle_repository = _wire(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    investors = _persist_investors(client, cycle_repository, cycle_hash)
    assert investors.status_code == 200, investors.text
    investors_hash = investors.json()["data"]["persistence"]["synthesisHash"]

    contract_response = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis/input-contract"
    )
    contract = contract_response.json()["data"]
    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json={
            "modelProvider": "external_model_provider",
            "modelName": "athena-research-synthesis",
            "modelVersion": "2026-02",
            "inputFingerprint": contract["inputFingerprint"],
            "generatedAt": (AS_OF + timedelta(minutes=1)).isoformat(),
            "summary": "ATHENA explains the filing evidence for human review.",
            "rationale": "The narrative is bound to the complete Investors evidence and synthesis artifact.",
            "uncertainties": ["The future operating outcome remains uncertain."],
            "evidenceIds": contract["evidenceIds"],
        },
    )
    assert response.status_code == 200, response.text
    synthesis = response.json()["data"]["synthesis"]
    assert synthesis["investorsSynthesisHash"] == investors_hash
    assert synthesis["inputFingerprint"] == contract["inputFingerprint"]
    assert synthesis["recommendationInfluence"] is False
    assert synthesis["automaticTrading"] is False

    reread = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis"
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["data"]["persistence"]["investorsSynthesisHash"] == investors_hash
    assert reread.json()["data"]["synthesis"] == synthesis


def test_investors_synthesis_rejects_fmp_model_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cycle_repository = _wire(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    response = _persist_investors(client, cycle_repository, cycle_hash, provider="FMP")
    assert response.status_code == 400
    assert "FMP" in response.json()["detail"]


def test_athena_rejects_stale_pre_investors_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cycle_repository = _wire(tmp_path, monkeypatch)
    client = TestClient(app)
    cycle_hash = _create_cycle(client)
    persisted = _persist_investors(client, cycle_repository, cycle_hash)
    assert persisted.status_code == 200
    record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    contract = athena_api._cycle_evidence_contract(record)
    stale = athena_api._base_input_fingerprint(record, None, contract)
    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/athena-synthesis",
        json={
            "modelProvider": "external_model_provider",
            "modelName": "athena-research-synthesis",
            "modelVersion": "2026-02",
            "inputFingerprint": stale,
            "generatedAt": (AS_OF + timedelta(minutes=1)).isoformat(),
            "summary": "Stale synthesis.",
            "rationale": "This deliberately omits the Investors synthesis binding.",
            "uncertainties": ["Uncertain."],
            "evidenceIds": ["a" * 64],
        },
    )
    assert response.status_code == 400
    assert "canónicos" in response.json()["detail"]
