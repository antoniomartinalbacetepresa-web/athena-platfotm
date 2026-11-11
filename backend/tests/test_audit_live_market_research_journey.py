"""Offline contract tests: fixtures never constitute live-market evidence."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.audit_live_market_research_journey import (
    AuditBlocked, MODULES, audit_journey, make_fetch,
)

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)


def _responses():
    stamp = (NOW - timedelta(minutes=10)).isoformat()
    return {
        "/api/v1/market/quote": {"data": {
            "symbol": "AAPL", "close": 123.45, "sourceProvider": "yahoo",
            "retrievedAt": stamp, "timestamp": stamp,
            "quoteMode": "provider_fast_info", "realTimePriceVerified": False,
            "historicalPointInTimeEligible": False,
            "canonicalIdentityStatus": "matched_internal_listing", "instrumentId": 17,
        }},
        "/api/v1/market/history": {
            "data": [
                {"symbol": "AAPL", "close": 101.0, "adjustedClose": 101.0,
                 "sourceProvider": "yahoo", "timestamp": (NOW - timedelta(days=380)).isoformat(),
                 "retrievedAt": stamp, "dividend": None, "stockSplit": None},
                {"symbol": "AAPL", "close": 123.0, "adjustedClose": 122.0,
                 "sourceProvider": "yahoo", "timestamp": (NOW - timedelta(days=3)).isoformat(),
                 "retrievedAt": stamp, "dividend": 0.2, "stockSplit": None},
            ],
            "provenance": {"retrievalMode": "current_provider_history",
                           "historicalPointInTimeEligible": False,
                           "productionCoverageClaimed": False,
                           "sourceProviders": ["yahoo"], "retrievedAt": stamp},
        },
        "/api/v1/news/feed": {
            "query": '"AAPL" stock earnings', "advisoryStatus": "no_advice",
            "productionEligible": False, "sourceProvider": "google_news_rss",
            "retrievedAt": stamp,
            "policy": {"automaticTrading": False, "athenaRecommendationInfluence": False},
            "items": [{"publisher": "Example", "sourceProvider": "google_news_rss",
                       "publishedAt": stamp, "retrievedAt": stamp,
                       "articleUrl": "https://news.example.org/article"}],
        },
        "/api/v1/recommendations/production/professional-dossier": {"data": {
            "symbol": "AAPL", "instrumentId": 17, "asOf": stamp,
            "advisoryStatus": "no_advice", "readOnly": True,
            "productionEligible": False, "allocationEligible": False,
            "executionEligible": False, "orderRoutingEligible": False,
            "automaticTrading": False,
            "professionalModules": {
                name: {"productionEligible": False, "status": "pending", "evidence": None}
                for name in MODULES
            },
        }},
    }


def _audit(responses):
    seen = []

    def fetch(path, params):
        seen.append((path, params))
        return responses[path]

    return audit_journey(fetch, symbol="aapl", now=NOW), seen


def test_audit_reports_gaps_without_fabricating_evidence():
    report, seen = _audit(_responses())
    assert report["status"] == "incomplete_evidence"
    assert report["dossier"]["evidenceAttachedCount"] == 0
    assert len(report["dossier"]["modulesWithoutEvidence"]) == 11
    assert seen[-1][1] == {"symbol": "AAPL", "instrumentId": "17"}
    assert report["history"]["has365CalendarDaySpan"] is True
    assert report["history"]["latestObservationAgeCalendarDays"] == 3
    assert report["history"]["current365DayCoverageCandidate"] is True
    assert report["history"]["continuityVerified"] is False
    assert report["history"]["candidateWeekdayGapCount"] > 0
    assert report["history"]["dividendEventRows"] == 1
    assert report["completeResearchVerified"] is False
    assert report["quote"]["realTimeVerified"] is False
    assert report["news"]["issuerIdentityIndependentlyVerified"] is False


def test_partial_evidence_is_not_claimed_as_full_coverage():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    report, _ = _audit(responses)
    assert report["status"] == "partial_research_evidence"
    assert report["dossier"]["modulesWithEvidence"] == ["factorRisk"]
    assert report["dossier"]["evidenceAttachedCount"] == 1


@pytest.mark.parametrize("path,mutate", [
    ("/api/v1/market/quote", lambda x: x["data"].update(symbol="MSFT")),
    ("/api/v1/market/quote", lambda x: x["data"].update(close=float("nan"))),
    ("/api/v1/market/quote", lambda x: x["data"].update(instrumentId=18, canonicalIdentityStatus="unresolved")),
    ("/api/v1/market/history", lambda x: x["data"][0].update(symbol="MSFT")),
    ("/api/v1/market/history", lambda x: x["data"][0].update(close=-1.0)),
    ("/api/v1/market/history", lambda x: x["provenance"].update(historicalPointInTimeEligible=True)),
    ("/api/v1/news/feed", lambda x: x.update(query="stock market")),
    ("/api/v1/news/feed", lambda x: x["items"][0].update(articleUrl="http://insecure.example.org/a")),
    ("/api/v1/news/feed", lambda x: x["items"][0].update(sourceProvider="another_provider")),
    ("/api/v1/news/feed", lambda x: x["policy"].update(automaticTrading=True)),
    ("/api/v1/recommendations/production/professional-dossier", lambda x: x["data"].update(instrumentId=18)),
    ("/api/v1/recommendations/production/professional-dossier", lambda x: x["data"].update(readOnly=False)),
    ("/api/v1/recommendations/production/professional-dossier", lambda x: x["data"]["professionalModules"].pop("factorRisk")),
])
def test_mismatched_or_unsafe_responses_fail_closed(path, mutate):
    responses = _responses()
    mutate(responses[path])
    with pytest.raises(AuditBlocked):
        _audit(responses)


def test_future_timestamps_fail_closed():
    responses = _responses()
    responses["/api/v1/market/quote"]["data"]["retrievedAt"] = (NOW + timedelta(hours=1)).isoformat()
    with pytest.raises(AuditBlocked, match="Future timestamp"):
        _audit(responses)


def test_only_https_or_local_loopback_http_allowed():
    for origin in ("http://example.com", "https://user:pass@example.com",
                   "https://example.com/path", "https://example.com?x=1"):
        with pytest.raises(AuditBlocked):
            make_fetch(origin)
    assert callable(make_fetch("http://127.0.0.1:8000"))


@pytest.mark.parametrize("symbol", ["AAPL\\\\", "AAPL/US", "", "A" * 22])
def test_invalid_symbol_never_reaches_live_transport(symbol):
    def fetch(_path, _params):
        raise AssertionError("invalid symbol must not reach network")
    with pytest.raises(AuditBlocked, match="Invalid symbol"):
        audit_journey(fetch, symbol=symbol, now=NOW)


def test_history_without_observations_reports_explicit_gap_not_coverage():
    responses = _responses()
    responses["/api/v1/market/history"]["data"] = []
    responses["/api/v1/market/history"]["provenance"]["sourceProviders"] = []
    responses["/api/v1/market/history"]["provenance"]["retrievedAt"] = None
    report, _ = _audit(responses)
    assert report["history"]["rows"] == 0
    assert report["history"]["has365CalendarDaySpan"] is False
    assert report["history"]["firstObservationUtcDate"] is None


def test_duplicate_daily_history_observation_fails_closed():
    responses = _responses()
    rows = responses["/api/v1/market/history"]["data"]
    rows.append(dict(rows[0]))
    with pytest.raises(AuditBlocked, match="Duplicate"):
        _audit(responses)


def test_history_corporate_actions_must_be_finite_positive():
    responses = _responses()
    responses["/api/v1/market/history"]["data"][0]["stockSplit"] = float("nan")
    with pytest.raises(AuditBlocked, match="corporate action"):
        _audit(responses)


def test_news_published_after_retrieval_is_rejected():
    responses = _responses()
    responses["/api/v1/news/feed"]["items"][0]["publishedAt"] = (NOW + timedelta(minutes=4)).isoformat()
    with pytest.raises(AuditBlocked, match="temporal provenance"):
        _audit(responses)


def test_year_long_but_stale_history_is_not_current_coverage():
    responses = _responses()
    rows = responses["/api/v1/market/history"]["data"]
    rows[0]["timestamp"] = (NOW - timedelta(days=395)).isoformat()
    rows[1]["timestamp"] = (NOW - timedelta(days=20)).isoformat()
    report, _ = _audit(responses)
    assert report["history"]["has365CalendarDaySpan"] is True
    assert report["history"]["latestObservationAgeCalendarDays"] == 20
    assert report["history"]["current365DayCoverageCandidate"] is False
    assert report["history"]["continuityVerified"] is False


@pytest.mark.parametrize("age,expected", [(7, True), (8, False)])
def test_current_history_candidate_requires_recent_last_observation(age, expected):
    responses = _responses()
    rows = responses["/api/v1/market/history"]["data"]
    rows[0]["timestamp"] = (NOW - timedelta(days=395)).isoformat()
    rows[1]["timestamp"] = (NOW - timedelta(days=age)).isoformat()
    report, _ = _audit(responses)
    assert report["history"]["current365DayCoverageCandidate"] is expected
    assert report["history"]["productionCoverageClaimed"] is False


def test_recent_history_with_less_than_one_year_is_not_coverage_candidate():
    responses = _responses()
    responses["/api/v1/market/history"]["data"][0]["timestamp"] = (
        NOW - timedelta(days=300)
    ).isoformat()
    report, _ = _audit(responses)
    assert report["history"]["current365DayCoverageCandidate"] is False


def test_quote_and_news_feed_freshness_are_reported_separately():
    responses = _responses()
    old = (NOW - timedelta(hours=30)).isoformat()
    responses["/api/v1/market/quote"]["data"].update(retrievedAt=old, timestamp=old)
    report, _ = _audit(responses)
    assert report["quote"]["staleOver24Hours"] is True
    assert report["news"]["feedStaleOver24Hours"] is False
    responses["/api/v1/news/feed"]["retrievedAt"] = old
    responses["/api/v1/news/feed"]["items"][0].update(retrievedAt=old, publishedAt=old)
    report, _ = _audit(responses)
    assert report["news"]["feedStaleOver24Hours"] is True
    assert report["completeResearchVerified"] is False


def test_fresh_quote_and_news_feed_have_explicit_nonstale_flags():
    report, _ = _audit(_responses())
    assert report["quote"]["staleOver24Hours"] is False
    assert report["news"]["feedStaleOver24Hours"] is False


def test_stale_quote_or_news_cannot_be_reported_as_partial_current_research():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    assert _audit(responses)[0]["status"] == "partial_research_evidence"
    old = (NOW - timedelta(hours=30)).isoformat()
    responses["/api/v1/market/quote"]["data"].update(retrievedAt=old, timestamp=old)
    assert _audit(responses)[0]["status"] == "stale_research_evidence"
    responses["/api/v1/market/quote"]["data"].update(retrievedAt=(NOW - timedelta(minutes=10)).isoformat(), timestamp=(NOW - timedelta(minutes=10)).isoformat())
    responses["/api/v1/news/feed"]["retrievedAt"] = old
    responses["/api/v1/news/feed"]["items"][0].update(retrievedAt=old, publishedAt=old)
    assert _audit(responses)[0]["status"] == "stale_research_evidence"


def test_stale_history_cannot_masquerade_as_current_partial_research():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    rows = responses["/api/v1/market/history"]["data"]
    rows[0]["timestamp"] = (NOW - timedelta(days=395)).isoformat()
    rows[1]["timestamp"] = (NOW - timedelta(days=20)).isoformat()
    report, _ = _audit(responses)
    assert report["quote"]["staleOver24Hours"] is False
    assert report["news"]["feedStaleOver24Hours"] is False
    assert report["history"]["current365DayCoverageCandidate"] is False
    assert report["status"] == "stale_research_evidence"
    assert report["completeResearchVerified"] is False


def test_missing_history_cannot_be_reported_as_partial_research():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    responses["/api/v1/market/history"]["data"] = []
    responses["/api/v1/market/history"]["provenance"]["sourceProviders"] = []
    responses["/api/v1/market/history"]["provenance"]["retrievedAt"] = None
    report, _ = _audit(responses)
    assert report["history"]["current365DayCoverageCandidate"] is False
    assert report["dossier"]["evidenceAttachedCount"] == 1
    assert report["status"] == "incomplete_evidence"
    assert report["completeResearchVerified"] is False


def test_short_history_cannot_be_reported_as_partial_research():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    responses["/api/v1/market/history"]["data"][0]["timestamp"] = (NOW - timedelta(days=300)).isoformat()
    report, _ = _audit(responses)
    assert report["history"]["current365DayCoverageCandidate"] is False
    assert report["status"] == "incomplete_evidence"


def test_stale_dossier_cannot_masquerade_as_current_partial_research():
    responses = _responses()
    dossier = responses["/api/v1/recommendations/production/professional-dossier"]["data"]
    dossier["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    assert _audit(responses)[0]["status"] == "partial_research_evidence"
    dossier["asOf"] = (NOW - timedelta(hours=30)).isoformat()
    report, _ = _audit(responses)
    assert report["status"] == "stale_research_evidence"
    assert report["dossier"]["staleOver24Hours"] is True
    assert report["dossier"]["ageHours"] == 30.0
    assert report["completeResearchVerified"] is False


def test_fresh_dossier_exposes_age_without_claiming_production():
    report, _ = _audit(_responses())
    assert report["dossier"]["staleOver24Hours"] is False
    assert report["dossier"]["ageHours"] == 0.17
    assert report["completeResearchVerified"] is False
