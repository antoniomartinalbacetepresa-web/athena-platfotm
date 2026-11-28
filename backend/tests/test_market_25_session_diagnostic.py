"""Synthetic API contract checks; these do not establish provider rights."""
from datetime import datetime, timedelta, timezone

from app.api import market


def _history(count: int = 26):
    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [
        {
            "symbol": "MSFT",
            "timestamp": (first + timedelta(days=i)).isoformat(),
            "close": 101.0,
            "low": 80.0 if i == 3 else (50.0 if i == 25 else 99.0),
            "volume": 1000,
            "sourceProvider": "synthetic-not-licensed",
        }
        for i in range(count)
    ]


def test_previous_25_session_low_excludes_evaluation_bar(monkeypatch):
    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: _history())
    data = market.get_opportunity_pattern_readiness(symbol="MSFT")["data"]
    assert data["previous25SessionReferenceComplete"] is True
    assert data["previous25SessionLowDiagnostic"] == 80.0
    assert data["previous25SessionReferenceEndsOn"] == "2026-09-25"
    assert data["previous25SessionEvaluationDate"] == "2026-09-26"
    assert data["previous25SessionSignalEligible"] is False
    assert data["licenceVerified"] is False
    assert data["patternComputed"] is False


def test_previous_25_session_low_requires_26_complete_low_observations(monkeypatch):
    incomplete = _history()
    incomplete[7].pop("low")
    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: incomplete)
    data = market.get_opportunity_pattern_readiness(symbol="MSFT")["data"]
    assert data["previous25SessionReferenceComplete"] is False
    assert data["previous25SessionLowDiagnostic"] is None

    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: _history(25))
    data = market.get_opportunity_pattern_readiness(symbol="MSFT")["data"]
    assert data["previous25SessionReferenceComplete"] is False
    assert data["previous25SessionLowDiagnostic"] is None
