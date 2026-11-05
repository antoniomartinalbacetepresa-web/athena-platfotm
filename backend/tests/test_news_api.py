from __future__ import annotations

import pytest
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


def test_news_api_rejects_automatic_scoring_policy(monkeypatch) -> None:
    payload = _safe_payload()
    payload["policy"]["automaticScoring"] = True
    monkeypatch.setattr(news_api, "_news_service", FakeNewsService(payload))

    response = TestClient(app).get("/api/v1/news/feed")

    assert response.status_code == 500
    assert response.json()["detail"] == "Contrato de noticias inseguro."


def test_news_api_rejects_invalid_query_parameters_without_calling_service(monkeypatch) -> None:
    fake = FakeNewsService(_safe_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)

    response = TestClient(app).get("/api/v1/news/feed", params={"limit": 0})

    assert response.status_code == 422
    assert fake.calls == []


def _company_payload() -> dict:
    payload = _safe_payload()
    payload["items"][0]["title"] = "Acme announces quarterly results"
    payload["query"] = '"Acme Corporation" ACME'
    return payload


def test_company_news_api_returns_read_only_radar_evidence_with_provenance(monkeypatch) -> None:
    fake = FakeNewsService(_company_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "acme"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "news_evidence_ready"
    assert data["acceptedCount"] == 1
    assert data["evidence"][0]["category"] == "news"
    assert data["evidence"][0]["provider"] == "google_news_rss"
    assert data["evidence"][0]["publishedAt"] == "2026-09-04T07:00:00+00:00"
    assert data["evidence"][0]["availableAt"] == "2026-09-04T08:00:00+00:00"
    assert data["advisoryStatus"] == "no_advice"
    assert data["readOnly"] is True
    for key in (
        "productionEligible", "licenseVerified", "modelExecutionVerified",
        "persisted", "issuerIdentityIndependentlyVerified",
        "independentCorroborationClaimed", "recommendationInfluence",
        "automaticScoring", "automaticTrading",
    ):
        assert data[key] is False
    assert fake.calls == [{"query": '"Acme Corporation" ACME', "limit": 8}]


def test_company_news_api_exposes_unavailable_not_fake_evidence(monkeypatch) -> None:
    payload = _company_payload()
    payload["items"][0]["title"] = "Unrelated company reports results"
    monkeypatch.setattr(news_api, "_news_service", FakeNewsService(payload))
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "news_evidence_unavailable"
    assert data["acceptedCount"] == 0
    assert data["rejectedCount"] == 1
    assert data["evidence"] == []
    assert data["provenanceComplete"] is False


def test_company_news_api_does_not_replay_live_news_into_historical_pit(monkeypatch) -> None:
    fake = FakeNewsService(_company_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME",
                "asOf": "2026-09-04T07:59:59+00:00"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["acceptedCount"] == 0
    assert data["asOf"] == "2026-09-04T07:59:59+00:00"
    assert data["persisted"] is False


def test_company_news_api_rejects_future_cutoff_before_provider_call(monkeypatch) -> None:
    fake = FakeNewsService(_company_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME",
                "asOf": "2099-01-01T00:00:00+00:00"},
    )
    assert response.status_code == 400
    assert fake.calls == []


def test_company_news_api_rejects_tampered_provider_policy(monkeypatch) -> None:
    fake = FakeNewsService(_company_payload())
    fake.payload["policy"]["automaticTrading"] = True
    monkeypatch.setattr(news_api, "_news_service", fake)
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME"},
    )
    assert response.status_code == 502
    assert "provenance" in response.json()["detail"]


def test_company_news_api_rejects_bad_symbol_before_provider_call(monkeypatch) -> None:
    fake = FakeNewsService(_company_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME OR BAD"},
    )
    assert response.status_code == 422
    assert fake.calls == []


def test_company_news_evidence_roundtrips_to_radar_without_losing_provenance(monkeypatch) -> None:
    """Exercise the actual News HTTP output as Radar HTTP input, without a fake issuer binding."""
    fake = FakeNewsService(_company_payload())
    monkeypatch.setattr(news_api, "_news_service", fake)
    client = TestClient(app)
    news = client.get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Acme Corporation", "symbol": "ACME"},
    )
    assert news.status_code == 200
    evidence = news.json()["data"]
    assert evidence["acceptedCount"] == 1
    radar = client.post(
        "/api/v1/recommendations/professional-research/athena-radar",
        json={
            "asOf": evidence["retrievedAt"],
            "candidates": [{
                "instrumentId": "fixture:acme:unverified-issuer",
                "symbol": evidence["symbol"],
                "evidence": evidence["evidence"],
            }],
        },
    )
    assert radar.status_code == 200, radar.text
    data = radar.json()["data"]
    item = data["candidates"][0]["evidence"][0]
    assert item["provider"] == "google_news_rss"
    assert item["publisher"] == "Reuters"
    assert item["publishedAt"] == "2026-09-04T07:00:00+00:00"
    assert item["availableAt"] == "2026-09-04T08:00:00+00:00"
    assert item["sourceRef"] == "https://news.google.com/rss/articles/one"
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["policy"]["automaticTrading"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", None),
        ("publisher", None),
        ("publishedAt", None),
        ("publishedAt", "2026-09-04T09:00:00+00:00"),
        ("sourceRef", "http://news.example.test/unsafe"),
    ],
)
def test_radar_http_rejects_missing_or_invalid_structured_news_provenance(
    field: str, value: str | None,
) -> None:
    item = {
        "evidenceId": "news:fixture",
        "category": "news",
        "urgency": "routine",
        "summary": "Acme announces quarterly results",
        "availableAt": "2026-09-04T08:00:00+00:00",
        "source": "news",
        "sourceRef": "https://news.google.com/rss/articles/one",
        "provider": "google_news_rss",
        "publisher": "Reuters",
        "publishedAt": "2026-09-04T07:00:00+00:00",
    }
    item[field] = value
    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/athena-radar",
        json={
            "asOf": "2026-09-04T08:00:00+00:00",
            "candidates": [{
                "instrumentId": "fixture:acme:unverified-issuer",
                "symbol": "ACME",
                "evidence": [item],
            }],
        },
    )
    assert response.status_code == 400
