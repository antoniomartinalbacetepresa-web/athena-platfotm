"""Fail-closed API regression for contradictory provider daily candles.

Synthetic provider fixtures only: these tests do not establish licensing or PIT.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.market import get_history


def _bar(**overrides):
    bar = {
        "symbol": "MSFT",
        "timestamp": "2026-01-05T00:00:00+00:00",
        "sourceProvider": "synthetic-test",
        "retrievedAt": "2026-01-06T00:00:00+00:00",
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": 105.0,
        "adjustedClose": 104.0,
        "volume": 1000.0,
    }
    bar.update(overrides)
    return bar


@pytest.mark.parametrize("overrides", [
    {"high": 89.0},
    {"low": 111.0},
    {"high": 95.0},
    {"low": 106.0},
    {"open": 111.0},
    {"open": 89.0},
    {"high": float("nan")},
    {"adjustedClose": -1.0},
    {"open": True},
])
def test_history_rejects_contradictory_ohlc(overrides):
    with patch("app.api.market.market_service.get_history", return_value=[_bar(**overrides)]):
        with pytest.raises(HTTPException) as exc:
            get_history(symbol="MSFT")
    assert exc.value.status_code == 502


def test_history_accepts_consistent_ohlc_without_pit_promotion():
    with patch("app.api.market.market_service.get_history", return_value=[_bar()]):
        response = get_history(symbol="MSFT")
    assert len(response["data"]) == 1
    assert response["provenance"]["historicalPointInTimeEligible"] is False
    assert response["provenance"]["licenceVerified"] is False


def test_history_accepts_missing_optional_ohlc_without_fabrication():
    with patch("app.api.market.market_service.get_history", return_value=[
        _bar(open=None, high=None, low=None, adjustedClose=None)
    ]):
        response = get_history(symbol="MSFT")
    assert response["data"][0]["high"] is None


def test_history_exposes_observation_bounds_and_missing_volume():
    earlier = _bar(timestamp="2026-01-02T00:00:00+00:00", volume=None)
    later = _bar(timestamp="2026-01-05T00:00:00+00:00")
    with patch("app.api.market.market_service.get_history", return_value=[later, earlier]):
        provenance = get_history(symbol="MSFT")["provenance"]
    assert provenance["firstObservedAt"] == "2026-01-02T00:00:00+00:00"
    assert provenance["lastObservedAt"] == "2026-01-05T00:00:00+00:00"
    assert provenance["missingVolumeCount"] == 1
    assert provenance["historicalPointInTimeEligible"] is False
    assert provenance["licenceVerified"] is False


def test_empty_history_has_explicit_empty_coverage():
    with patch("app.api.market.market_service.get_history", return_value=[]):
        provenance = get_history(symbol="MSFT")["provenance"]
    assert provenance["historyStatus"] == "empty"
    assert provenance["firstObservedAt"] is None
    assert provenance["lastObservedAt"] is None
    assert provenance["missingVolumeCount"] == 0


@pytest.mark.parametrize("retrieved_at", [
    "2026-01-04T23:59:59+00:00",
    "2099-01-01T00:00:00+00:00",
    "2026-01-06T00:00:00",
    "not-a-date",
])
def test_history_rejects_impossible_retrieval_provenance(retrieved_at):
    with patch("app.api.market.market_service.get_history", return_value=[
        _bar(retrievedAt=retrieved_at)
    ]):
        with pytest.raises(HTTPException) as exc:
            get_history(symbol="MSFT")
    assert exc.value.status_code == 502


def test_history_missing_retrieval_is_not_pit_verified():
    with patch("app.api.market.market_service.get_history", return_value=[
        _bar(retrievedAt=None)
    ]):
        provenance = get_history(symbol="MSFT")["provenance"]
    assert provenance["retrievedAt"] is None
    assert provenance["historicalPointInTimeEligible"] is False
    assert provenance["licenceVerified"] is False


def test_history_reports_observation_age_span_and_missing_retrieval():
    earlier = _bar(timestamp="2026-01-02T00:00:00+00:00", retrievedAt=None)
    later = _bar(timestamp="2026-01-05T00:00:00+00:00")
    with patch("app.api.market.market_service.get_history", return_value=[later, earlier]):
        provenance = get_history(symbol="MSFT")["provenance"]
    assert provenance["observationSpanDays"] == 3
    assert provenance["latestObservationAgeDays"] >= 0
    assert provenance["missingRetrievalCount"] == 1
    assert provenance["licenceVerified"] is False


def test_empty_history_reports_unknown_age_and_span():
    with patch("app.api.market.market_service.get_history", return_value=[]):
        provenance = get_history(symbol="MSFT")["provenance"]
    assert provenance["observationSpanDays"] is None
    assert provenance["latestObservationAgeDays"] is None
    assert provenance["missingRetrievalCount"] == 0
