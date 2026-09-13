from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
RETRIEVED_AT = AS_OF - timedelta(hours=1)
PUBLISHED_AT = RETRIEVED_AT - timedelta(minutes=30)


def _payload(*, category: str, provider: str | None, publisher: str | None) -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "radarEvidence": [
            {
                "evidenceId": f"{category}-1",
                "category": category,
                "urgency": "material",
                "summary": "Structured external evidence for human research review.",
                "availableAt": RETRIEVED_AT.isoformat(),
                "source": "news" if category == "news" else "Apple Investor Relations",
                "sourceRef": (
                    "https://example.com/news/aapl"
                    if category == "news"
                    else "https://investor.apple.com/example-filing"
                ),
                "provider": provider,
                "publisher": publisher,
                "publishedAt": PUBLISHED_AT.isoformat(),
            }
        ],
        "journalId": f"journal-{category}",
        "revisionId": "revision-1",
        "recordedAt": RETRIEVED_AT.isoformat(),
        "thesis": "Frozen thesis before outcome evidence.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-1",
                "kind": "assumption",
                "availableAt": (RETRIEVED_AT - timedelta(minutes=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:journal:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-1",
                "kind": "alternative_explanation",
                "claim": "Alternative explanation requires human review.",
                "strength": "material",
                "availableAt": RETRIEVED_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:1",
            }
        ],
    }


def _client_with_temp_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    database = AthenaDatabase(tmp_path / "external-provenance-cycle.db")
    monkeypatch.setattr(
        cycle_api,
        "journal_repository",
        RecommendationInvestmentJournalRepository(database),
    )
    monkeypatch.setattr(
        cycle_api,
        "cycle_repository",
        RecommendationProfessionalResearchCycleRepository(database),
    )
    return TestClient(app)


def test_cycle_api_transports_structured_news_provenance_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client_with_temp_repositories(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(
            category="news",
            provider="google_news_rss",
            publisher="Example Publisher",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    cycle_hash = data["integrity"]["cycleHash"]
    persisted = cycle_api.cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    evidence = persisted["package"]["radar"]["candidates"][0]["evidence"][0]
    assert evidence["provider"] == "google_news_rss"
    assert evidence["publisher"] == "Example Publisher"
    assert evidence["publishedAt"] == PUBLISHED_AT.isoformat()
    assert evidence["availableAt"] == RETRIEVED_AT.isoformat()
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False


def test_cycle_api_transports_structured_investor_provenance_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client_with_temp_repositories(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(
            category="investors",
            provider="issuer_ir",
            publisher="Apple Inc.",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    cycle_hash = data["integrity"]["cycleHash"]
    persisted = cycle_api.cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    evidence = persisted["package"]["radar"]["candidates"][0]["evidence"][0]
    assert evidence["provider"] == "issuer_ir"
    assert evidence["publisher"] == "Apple Inc."
    assert evidence["sourceRef"].startswith("https://investor.apple.com/")
    assert data["policy"]["automaticTrading"] is False


def test_cycle_api_rejects_news_when_structured_provenance_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client_with_temp_repositories(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(category="news", provider=None, publisher="Example Publisher"),
    )

    assert response.status_code == 400
    assert "requiere provider explícito" in response.json()["detail"]
