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
        "/api/v1/news/feed": {
            "query": '"AAPL" stock earnings', "advisoryStatus": "no_advice",
            "productionEligible": False, "sourceProvider": "google_news_rss",
            "retrievedAt": stamp,
            "policy": {"automaticTrading": False, "athenaRecommendationInfluence": False},
            "items": [{"publisher": "Example", "sourceProvider": "google_news_rss",
                       "publishedAt": stamp, "retrievedAt": stamp}],
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
    assert report["quote"]["realTimeVerified"] is False
    assert report["news"]["issuerIdentityIndependentlyVerified"] is False


def test_partial_evidence_is_not_claimed_as_full_coverage():
    responses = _responses()
    responses["/api/v1/recommendations/production/professional-dossier"]["data"]["professionalModules"]["factorRisk"]["evidence"] = {"source": "example"}
    report, _ = _audit(responses)
    assert report["status"] == "evidence_present"
    assert report["dossier"]["modulesWithEvidence"] == ["factorRisk"]
    assert report["dossier"]["evidenceAttachedCount"] == 1


@pytest.mark.parametrize("path,mutate", [
    ("/api/v1/market/quote", lambda x: x["data"].update(symbol="MSFT")),
    ("/api/v1/market/quote", lambda x: x["data"].update(close=float("nan"))),
    ("/api/v1/market/quote", lambda x: x["data"].update(instrumentId=18, canonicalIdentityStatus="unresolved")),
    ("/api/v1/news/feed", lambda x: x.update(query="stock market")),
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
