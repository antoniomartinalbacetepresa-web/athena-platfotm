from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.news as news_api
from app.main import app


class FakeNewsService:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def get_feed(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.payload


def _safe_payload() -> dict:
    return {
        "status": "news_feed_ready",
        "query": "markets",
        "count": 1,
        "sourceProvider": "google_news_rss",
        "retrievedAt": "2026-09-04T08:00:00+00:00",
        "items": [
            {
                "title": "Market update",
                "publisher": "Reuters",
                "publisherUrl": "https://www.reuters.com",
                "articleUrl": "https://news.google.com/rss/articles/one",
                "publishedAt": "2026-09-04T07:00:00+00:00",
                "retrievedAt": "2026-09-04T08:00:00+00:00",
                "sourceProvider": "google_news_rss",
            }
        ],
        "policy": {
            "athenaRecommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_news_api_exposes_traceable_parallel_evidence(monkeypatch) -> None:
    fake = FakeNewsService(_safe_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)

    response = TestClient(app).get(
        "/api/v1/news/feed",
        params={"query": "markets", "limit": 6, "language": "en", "country": "US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sourceProvider"] == "google_news_rss"
    assert body["advisoryStatus"] == "no_advice"
    assert body["productionEligible"] is False
    assert body["items"][0]["publisher"] == "Reuters"
    assert fake.calls == [
        {"query": "markets", "limit": 6, "language": "en", "country": "US"}
    ]


def test_news_api_fails_closed_if_news_attempts_to_influence_athena(monkeypatch) -> None:
    payload = _safe_payload()
    payload["policy"]["athenaRecommendationInfluence"] = True
    monkeypatch.setattr(news_api, "_news_service", FakeNewsService(payload))

    response = TestClient(app).get("/api/v1/news/feed")

    assert response.status_code == 500
    assert response.json()["detail"] == "Contrato de noticias inseguro."


def test_news_api_fails_closed_if_news_becomes_productive_or_trading(monkeypatch) -> None:
    payload = _safe_payload()
    payload["productionEligible"] = True
    monkeypatch.setattr(news_api, "_news_service", FakeNewsService(payload))
    assert TestClient(app).get("/api/v1/news/feed").status_code == 500

    payload = _safe_payload()
    payload["policy"]["automaticTrading"] = True
    monkeypatch.setattr(news_api, "_news_service", FakeNewsService(payload))
    assert TestClient(app).get("/api/v1/news/feed").status_code == 500


def test_news_api_rejects_invalid_query_parameters_without_calling_service(monkeypatch) -> None:
    fake = FakeNewsService(_safe_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)

    response = TestClient(app).get("/api/v1/news/feed", params={"limit": 0})

    assert response.status_code == 422
    assert fake.calls == []
