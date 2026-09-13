from __future__ import annotations

from datetime import datetime, timezone

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_news_evidence_service import RecommendationNewsEvidenceService


class FakeNewsService:
    def __init__(self, items: list[dict], provider: str = "google_news_rss") -> None:
        self.items = items
        self.provider = provider
        self.calls: list[dict] = []

    def get_feed(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "status": "news_feed_ready",
            "sourceProvider": self.provider,
            "items": self.items,
        }


def _valid_item(**overrides) -> dict:
    item = {
        "title": "Acme reports quarterly results",
        "publisher": "Reuters",
        "publisherUrl": "https://www.reuters.com",
        "articleUrl": "https://news.google.com/rss/articles/acme-results",
        "publishedAt": "2026-09-12T10:00:00+00:00",
        "retrievedAt": "2026-09-12T10:05:00+00:00",
        "sourceProvider": "google_news_rss",
    }
    item.update(overrides)
    return item


def test_news_evidence_preserves_structured_provenance_and_pit_availability() -> None:
    fake = FakeNewsService([_valid_item()])
    result = RecommendationNewsEvidenceService(news_service=fake).build_company_evidence(
        company_name="Acme Corporation",
        symbol="acme",
    )

    assert fake.calls == [{"query": '"Acme Corporation" ACME', "limit": 8}]
    assert result["status"] == "news_evidence_ready"
    assert result["sourceProvider"] == "google_news_rss"
    assert result["acceptedCount"] == 1
    assert result["rejectedCount"] == 0
    assert result["provenanceComplete"] is True
    assert result["productionTruthClaimed"] is False
    assert result["independentCorroborationClaimed"] is False
    assert result["recommendationInfluence"] is False
    assert result["automaticScoring"] is False
    assert result["automaticTrading"] is False

    evidence = result["evidence"][0]
    assert evidence.category == "news"
    assert evidence.source == "news"
    assert evidence.provider == "google_news_rss"
    assert evidence.publisher == "Reuters"
    assert evidence.source_ref == "https://news.google.com/rss/articles/acme-results"
    assert evidence.published_at == datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    assert evidence.available_at == datetime(2026, 9, 12, 10, 5, tzinfo=timezone.utc)

    radar = RecommendationAthenaRadarService().build(
        as_of=datetime(2026, 9, 12, 10, 6, tzinfo=timezone.utc),
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-acme",
                symbol="ACME",
                evidence=result["evidence"],
            ),
        ),
    ).to_api_dict()
    api_evidence = radar["candidates"][0]["evidence"][0]
    assert api_evidence["source"] == "news"
    assert api_evidence["sourceRef"] == "https://news.google.com/rss/articles/acme-results"
    assert api_evidence["provider"] == "google_news_rss"
    assert api_evidence["publisher"] == "Reuters"
    assert api_evidence["publishedAt"] == "2026-09-12T10:00:00+00:00"
    assert api_evidence["availableAt"] == "2026-09-12T10:05:00+00:00"
    assert radar["productionEligible"] is False
    assert radar["policy"]["automaticTrading"] is False


def test_news_evidence_fails_closed_on_provider_mismatch_and_bad_items() -> None:
    bad_items = [
        _valid_item(articleUrl="http://unsafe.example/article"),
        _valid_item(publisher=""),
        _valid_item(publishedAt="2026-09-12T10:10:00+00:00"),
        _valid_item(sourceProvider="other_provider"),
    ]
    result = RecommendationNewsEvidenceService(
        news_service=FakeNewsService(bad_items)
    ).build_company_evidence(company_name="Acme", symbol="ACME")

    assert result["status"] == "news_evidence_unavailable"
    assert result["acceptedCount"] == 0
    assert result["rejectedCount"] == 4
    assert result["provenanceComplete"] is False
    assert result["productionTruthClaimed"] is False
    assert result["independentCorroborationClaimed"] is False


def test_news_evidence_rejects_feed_level_provider_mismatch() -> None:
    service = RecommendationNewsEvidenceService(
        news_service=FakeNewsService([_valid_item()], provider="other_provider")
    )

    try:
        service.build_company_evidence(company_name="Acme", symbol="ACME")
    except ValueError as exc:
        assert "proveedor" in str(exc)
    else:
        raise AssertionError("provider mismatch must fail closed")


def test_news_evidence_deduplicates_article_url_without_claiming_corroboration() -> None:
    duplicate = _valid_item(title="Syndicated duplicate")
    result = RecommendationNewsEvidenceService(
        news_service=FakeNewsService([_valid_item(), duplicate])
    ).build_company_evidence(company_name="Acme", symbol="ACME")

    assert result["acceptedCount"] == 1
    assert result["rejectedCount"] == 1
    assert result["independentCorroborationClaimed"] is False


def test_radar_rejects_publication_timestamp_after_observed_availability() -> None:
    item = _valid_item(
        publishedAt="2026-09-12T10:04:00+00:00",
        retrievedAt="2026-09-12T10:05:00+00:00",
    )
    result = RecommendationNewsEvidenceService(
        news_service=FakeNewsService([item])
    ).build_company_evidence(company_name="Acme", symbol="ACME")
    evidence = result["evidence"][0]

    mutated = type(evidence)(
        evidence_id=evidence.evidence_id,
        category=evidence.category,
        urgency=evidence.urgency,
        summary=evidence.summary,
        available_at=evidence.available_at,
        source=evidence.source,
        source_ref=evidence.source_ref,
        provider=evidence.provider,
        publisher=evidence.publisher,
        published_at=datetime(2026, 9, 12, 10, 6, tzinfo=timezone.utc),
    )
    try:
        RecommendationAthenaRadarService().build(
            as_of=datetime(2026, 9, 12, 10, 7, tzinfo=timezone.utc),
            candidates=(
                AthenaRadarCandidateInput(
                    instrument_id="instrument-acme",
                    symbol="ACME",
                    evidence=(mutated,),
                ),
            ),
        )
    except ValueError as exc:
        assert "published_at" in str(exc)
    else:
        raise AssertionError("publication after availability must fail closed")
