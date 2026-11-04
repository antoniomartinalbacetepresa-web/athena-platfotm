"""Private News -> ATHENA canonical cycle: synthetic HTTP/SQLite authorization regression.

No live provider, real model execution, or production data is used.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_athena_synthesis as athena_api
import app.api.recommendation_investment_journal as journal_api
import app.api.recommendation_news_synthesis as news_api
import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_news_evidence_service import RecommendationNewsEvidenceService
from app.services.recommendation_news_synthesis_service import RecommendationNewsSynthesisService
from test_live_company_news_research_cycle_api import FakeNewsService, _payload


PREFIX = "/api/v1/recommendations/professional-research/research-cycle"


def _setup(tmp_path, monkeypatch):
    database = AthenaDatabase(tmp_path / "private-synthesis.db")
    cycles = RecommendationProfessionalResearchCycleRepository(database)
    journals = RecommendationInvestmentJournalRepository(database)
    news = RecommendationNewsSynthesisRepository(database)
    athena = RecommendationAthenaSynthesisRepository(database)
    for module in (cycle_api, news_api, athena_api):
        monkeypatch.setattr(module, "cycle_repository", cycles)
    monkeypatch.setattr(cycle_api, "journal_repository", journals)
    monkeypatch.setattr(journal_api, "investment_journal_repository", journals)
    monkeypatch.setattr(
        cycle_api, "live_news_evidence_service",
        RecommendationNewsEvidenceService(news_service=FakeNewsService()),
    )
    monkeypatch.setattr(news_api, "synthesis_repository", news)
    monkeypatch.setattr(athena_api, "news_repository", news)
    monkeypatch.setattr(athena_api, "athena_repository", athena)
    monkeypatch.setitem(app.dependency_overrides, cycle_api.current_account, lambda: {"id": 17})
    return TestClient(app), cycles, news, athena


def _create_private_cycle(client):
    response = client.post(f"{PREFIX}/from-live-company-news", json=_payload())
    assert response.status_code == 200, response.text
    return response.json()["data"]["integrity"]["cycleHash"]


def _news_request(cycles, cycle_hash):
    record = cycles.get_by_hash(cycle_hash=cycle_hash, owner_id=17)
    radar = news_api._radar_from_cycle_record(record)
    evidence = radar.candidates[0].evidence[0]
    fingerprint = RecommendationNewsSynthesisService().evidence_fingerprint(
        instrument_id=radar.candidates[0].instrument_id,
        symbol=radar.candidates[0].symbol,
        evidence=evidence,
    )
    return {
        "minimumImportance": "low",
        "assessments": [{
            "evidenceId": evidence.evidence_id,
            "modelProvider": "external_model_provider",
            "modelName": "synthetic-news-model",
            "modelVersion": "test-only",
            "inputFingerprint": fingerprint,
            "generatedAt": record["as_of"],
            "summary": "Synthetic research context; human review required.",
            "importance": "high",
            "impactDirection": "uncertain",
            "impactMagnitude": 0.3,
            "confidence": 0.5,
        }],
    }


def _athena_request(contract):
    return {
        "modelProvider": "external_model_provider",
        "modelName": "synthetic-athena-model",
        "modelVersion": "test-only",
        "inputFingerprint": contract["inputFingerprint"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": "Synthetic evidence explanation for human review only.",
        "rationale": "All Radar evidence IDs are preserved and bound to canonical News.",
        "uncertainties": ["Source identity and licensing have not been independently verified."],
        "evidenceIds": contract["evidenceIds"],
    }


def test_private_cycle_can_continue_through_news_and_athena_without_public_exposure(
    tmp_path, monkeypatch,
):
    client, cycles, news, athena = _setup(tmp_path, monkeypatch)
    cycle_hash = _create_private_cycle(client)
    public = f"{PREFIX}/{cycle_hash}"
    private = f"{PREFIX}/private/{cycle_hash}"
    assessment = _news_request(cycles, cycle_hash)

    # Public and other-owner routes fail closed BEFORE any synthesis is written.
    assert client.post(f"{public}/news-synthesis", json=assessment).status_code == 400
    assert client.get(f"{public}/news-synthesis").status_code == 404
    assert client.get(f"{public}/athena-synthesis/input-contract").status_code == 404
    monkeypatch.setitem(app.dependency_overrides, cycle_api.current_account, lambda: {"id": 23})
    assert client.post(f"{private}/news-synthesis", json=assessment).status_code == 404
    assert client.get(f"{private}/news-synthesis").status_code == 404
    assert client.get(f"{private}/athena-synthesis/input-contract").status_code == 404
    with pytest.raises(ValueError, match="no tiene síntesis News"):
        news.get_by_cycle_hash(cycle_hash=cycle_hash)

    monkeypatch.setitem(app.dependency_overrides, cycle_api.current_account, lambda: {"id": 17})
    saved_news = client.post(f"{private}/news-synthesis", json=assessment)
    assert saved_news.status_code == 200, saved_news.text
    assert saved_news.json()["data"]["synthesis"]["modelExecutionVerified"] is False
    assert client.get(f"{private}/news-synthesis").status_code == 200
    assert client.get(f"{public}/news-synthesis").status_code == 404

    input_response = client.get(f"{private}/athena-synthesis/input-contract")
    assert input_response.status_code == 200, input_response.text
    contract = input_response.json()["data"]
    assert contract["evidenceIds"]
    request = _athena_request(contract)

    monkeypatch.setitem(app.dependency_overrides, cycle_api.current_account, lambda: {"id": 23})
    assert client.post(f"{private}/athena-synthesis", json=request).status_code == 404
    assert client.get(f"{private}/athena-synthesis").status_code == 404
    with pytest.raises(ValueError, match="no tiene ATHENA synthesis"):
        athena.get_by_cycle_hash(cycle_hash=cycle_hash)

    monkeypatch.setitem(app.dependency_overrides, cycle_api.current_account, lambda: {"id": 17})
    saved = client.post(f"{private}/athena-synthesis", json=request)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["synthesis"]["modelExecutionVerified"] is False
    assert saved.json()["data"]["artifactBindingVerified"] is True
    assert client.get(f"{private}/athena-synthesis").status_code == 200
    assert client.get(f"{public}/athena-synthesis").status_code == 404
    assert client.get(f"{public}/athena-synthesis/input-contract").status_code == 404


def test_private_synthesis_endpoints_require_authentication_before_access(
    tmp_path, monkeypatch,
):
    client, _, _, _ = _setup(tmp_path, monkeypatch)
    cycle_hash = _create_private_cycle(client)
    monkeypatch.delitem(app.dependency_overrides, cycle_api.current_account, raising=False)
    private = f"{PREFIX}/private/{cycle_hash}"
    for path in (
        f"{private}/news-synthesis",
        f"{private}/athena-synthesis",
        f"{private}/athena-synthesis/input-contract",
    ):
        assert client.get(path).status_code == 401
    assert client.post(f"{private}/news-synthesis", json={"assessments": []}).status_code == 401
    assert client.post(f"{private}/athena-synthesis", json={}).status_code == 401
