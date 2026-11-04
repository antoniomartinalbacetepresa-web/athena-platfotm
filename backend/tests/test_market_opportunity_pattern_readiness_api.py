"""Market-to-pattern evidence bridge: fail closed until independent verification."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import pytest

from app.api import market


def _rows(n=21):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "symbol": "MSFT",
            "timestamp": (start + timedelta(days=i)).isoformat(),
            "retrievedAt": "2026-02-01T12:00:00+00:00",
            "sourceProvider": "yahoo",
            "close": 100 + i,
            "volume": 1000,
        }
        for i in range(n)
    ]


def test_history_readiness_does_not_fabricate_licence_or_pit(monkeypatch):
    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: _rows())
    result = market.get_opportunity_pattern_readiness("MSFT")["data"]
    assert result["validDailySessions"] == 21
    assert result["minimum20SessionReferenceAvailable"] is True
    assert result["calendarSpanDays"] == 21
    assert result["history365CalendarSpanAvailable"] is False
    assert result["history365SessionCompletenessVerified"] is False
    assert result["latestObservationAgeCalendarDays"] >= 0
    assert result["checkedAt"].endswith("+00:00")
    assert result["sourceProviders"] == ["yahoo"]
    assert result["status"] == "blocked_unverified_market_evidence"
    assert result["licenceVerified"] is False
    assert result["corporateActionsIndependentlyVerified"] is False
    assert result["historicalPointInTimeEligible"] is False
    assert result["patternComputed"] is False
    assert result["automaticTrading"] is False
    assert result["advisoryStatus"] == "no_advice"


def test_bad_identity_duplicate_and_invalid_rows_are_not_counted(monkeypatch):
    rows = _rows(20)
    rows += [dict(rows[0]), {**rows[0], "symbol": "AAPL"},
             {**rows[0], "close": float("nan")}]
    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: rows)
    result = market.get_opportunity_pattern_readiness("MSFT")["data"]
    assert result["validDailySessions"] == 20
    assert result["invalidOrDuplicateRows"] == 3
    assert result["minimum20SessionReferenceAvailable"] is False
    assert result["patternComputed"] is False


def test_provider_failure_is_explicit(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(market.market_service, "get_history", fail)
    with pytest.raises(HTTPException) as exc:
        market.get_opportunity_pattern_readiness("MSFT")
    assert exc.value.status_code == 502


def test_future_provider_observations_do_not_count_toward_readiness(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(days=5)
    rows = _rows(20) + [{**_rows(1)[0], "timestamp": future.isoformat()}]
    monkeypatch.setattr(market.market_service, "get_history", lambda **kwargs: rows)
    result = market.get_opportunity_pattern_readiness("MSFT")["data"]
    assert result["validDailySessions"] == 20
    assert result["invalidOrDuplicateRows"] == 1
    assert result["minimum20SessionReferenceAvailable"] is False
    assert result["history365SessionCompletenessVerified"] is False
