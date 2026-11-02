"""Live company news -> persisted PIT research cycle: only server-observed news.

Synthetic feed responses exercise the HTTP/storage contract, NOT a licensed
real-world feed, deployment, issuer verification, or model execution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_news_evidence_service import RecommendationNewsEvidenceService


class FakeNewsService:
    def __init__(self, *, headline: str = "Acme announces quarterly results", unsafe: bool = False):
        self.headline = headline
        self.unsafe = unsafe
        self.calls = []

    def get_feed(self, **kwargs):
        self.calls.append(kwargs)
        retrieved = datetime.now(timezone.utc) - timedelta(minutes=2)
        published = retrieved - timedelta(hours=1)
        return {
            "status": "news_feed_ready",
            "query": '"Acme Corporation" ACME',
            "count": 1,
            "sourceProvider": "google_news_rss",
            "retrievedAt": retrieved.isoformat(),
            "items": [{
                "title": self.headline,
                "publisher": "Example Publisher",
                "articleUrl": ("http://unsafe.test/article" if self.unsafe
                               else "https://news.google.com/rss/articles/acme"),
                "publishedAt": published.isoformat(),
                "retrievedAt": retrieved.isoformat(),
                "sourceProvider": "google_news_rss",
            }],
            "policy": {
                "athenaRecommendationInfluence": False,
                "automaticScoring": False,
                "automaticTrading": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


def _payload():
    earlier = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    return {
        "instrumentId": "unverified:acme",
        "companyName": "Acme Corporation",
        "symbol": "ACME",
        "journalId": "journal-live-acme",
        "revisionId": "revision-1",
        "thesis": "Human-authored research question; no buy or sell recommendation.",
        "journalReferences": [{
            "referenceId": "human-ref-1",
            "kind": "assumption",
            "availableAt": earlier,
            "source": "human_research",
            "sourceRef": "urn:human:assumption:1",
        }],
        "contradictoryEvidence": [{
            "evidenceId": "human-contradiction-1",
            "kind": "alternative_explanation",
            "claim": "Other causes could explain the observed headline.",
            "strength": "material",
            "availableAt": earlier,
            "source": "human_research",
            "sourceRef": "urn:human:contradiction:1",
        }],
    }


def _setup(tmp_path, monkeypatch, fake, *, authenticated=True, owner_id=17):
    database = AthenaDatabase(tmp_path / "live-news-cycle.db")
    monkeypatch.setattr(cycle_api, "journal_repository", RecommendationInvestmentJournalRepository(database))
    monkeypatch.setattr(cycle_api, "cycle_repository", RecommendationProfessionalResearchCycleRepository(database))
    monkeypatch.setattr(
        cycle_api, "live_news_evidence_service",
        RecommendationNewsEvidenceService(news_service=fake),
    )
    if authenticated:
        monkeypatch.setitem(
            app.dependency_overrides,
            cycle_api.current_account,
            lambda: {"id": owner_id},
        )
    return TestClient(app)


def test_live_news_bridge_persists_server_retrieved_provenance_and_reloads(tmp_path, monkeypatch):
    fake = FakeNewsService()
    client = _setup(tmp_path, monkeypatch, fake)
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=_payload(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["cyclePersistence"]["packageIntegrityVerified"] is True
    assert data["journalPersistence"]["lineageVerified"] is True
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["humanReviewRequired"] is True
    assert data["liveNewsRetrieval"]["licenseVerified"] is False
    assert data["liveNewsRetrieval"]["historicalReplay"] is False
    assert data["liveNewsRetrieval"]["modelExecutionVerified"] is False
    assert data["liveNewsRetrieval"]["authenticatedWrite"] is True
    assert data["liveNewsRetrieval"]["ownerIsolationVerified"] is False
    assert data["liveNewsRetrieval"]["metadataPersistedInCanonicalCycle"] is False
    assert fake.calls == [{"query": '"Acme Corporation" ACME', "limit": 8}]
    cycle_hash = data["integrity"]["cycleHash"]
    persisted = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}"
    )
    assert persisted.status_code == 200, persisted.text
    package = persisted.json()["data"]["package"]
    item = package["radar"]["candidates"][0]["evidence"][0]
    assert item["category"] == "news"
    assert item["provider"] == "google_news_rss"
    assert item["publisher"] == "Example Publisher"
    assert item["sourceRef"] == "https://news.google.com/rss/articles/acme"
    assert item["availableAt"] <= package["cycle"]["asOf"]
    assert package["cycle"]["symbol"] == "ACME"


@pytest.mark.parametrize("headline,unsafe", [
    ("Unrelated company announces results", False),
    ("Acme announces quarterly results", True),
])
def test_live_news_bridge_rejects_empty_or_unsafe_news_without_storage(
    tmp_path, monkeypatch, headline, unsafe,
):
    fake = FakeNewsService(headline=headline, unsafe=unsafe)
    client = _setup(tmp_path, monkeypatch, fake)
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=_payload(),
    )
    assert response.status_code == 409
    with pytest.raises(ValueError, match="No existe un journal"):
        cycle_api.journal_repository.verify_lineage(journal_id="journal-live-acme")


def test_live_news_bridge_requires_human_thesis_and_contradictory_evidence(
    tmp_path, monkeypatch,
):
    fake = FakeNewsService()
    client = _setup(tmp_path, monkeypatch, fake)
    payload = _payload()
    payload.pop("thesis")
    assert client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=payload,
    ).status_code == 422
    payload = _payload()
    payload["contradictoryEvidence"] = []
    assert client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=payload,
    ).status_code == 422
    assert fake.calls == []


def test_direct_cycle_rejects_future_asof_before_any_storage(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, FakeNewsService())
    payload = _payload()
    payload.pop("companyName")
    payload["asOf"] = "2099-01-01T00:00:00+00:00"
    payload["recordedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    payload["radarEvidence"] = [{
        "evidenceId": "news:fixture",
        "category": "news",
        "urgency": "routine",
        "summary": "Acme announces quarterly results",
        "availableAt": payload["recordedAt"],
        "source": "news",
        "sourceRef": "https://news.google.com/rss/articles/acme",
        "provider": "google_news_rss",
        "publisher": "Example Publisher",
        "publishedAt": payload["recordedAt"],
    }]
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=payload,
    )
    assert response.status_code == 400
    assert "futuro" in response.json()["detail"]
    with pytest.raises(ValueError, match="No existe un journal"):
        cycle_api.journal_repository.verify_lineage(journal_id="journal-live-acme")



def test_live_news_bridge_rejects_anonymous_write_before_fetch_or_storage(tmp_path, monkeypatch):
    fake = FakeNewsService()
    client = _setup(tmp_path, monkeypatch, fake, authenticated=False)
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=_payload(),
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert fake.calls == []
    with pytest.raises(ValueError, match="No existe un journal"):
        cycle_api.journal_repository.verify_lineage(journal_id="journal-live-acme")


@pytest.mark.parametrize("owner_id", [0, -1, True, "17", None])
def test_live_news_bridge_rejects_invalid_account_context_before_fetch(
    tmp_path, monkeypatch, owner_id,
):
    fake = FakeNewsService()
    client = _setup(tmp_path, monkeypatch, fake, owner_id=owner_id)
    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle/from-live-company-news",
        json=_payload(),
    )
    assert response.status_code == 401
    assert fake.calls == []
    with pytest.raises(ValueError, match="No existe un journal"):
        cycle_api.journal_repository.verify_lineage(journal_id="journal-live-acme")
