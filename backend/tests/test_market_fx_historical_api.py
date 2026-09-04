from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

from app.api import market as market_api


class FakeHistoricalFxService:
    def __init__(self):
        self.calls = []

    def get_historical_rate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "fx_historical_ready",
            "baseCurrency": kwargs["base_currency"],
            "quoteCurrency": kwargs["quote_currency"],
            "rate": 0.92,
            "observedOn": kwargs["observed_on"].isoformat(),
            "observedAt": "2026-08-03T00:00:00+00:00",
            "retrievedAt": "2026-08-03T18:00:00+00:00",
            "knowledgeCutoff": kwargs["knowledge_cutoff"].isoformat(),
            "sourceProvider": "Yahoo Finance",
            "sourceSymbol": "USDEUR=X",
            "historicalPointInTimeEligible": True,
            "replayedFromPersistence": True,
        }


def test_operational_fx_service_has_persistent_pit_repository():
    assert market_api.fx_quote_service._repository is market_api.fx_rate_repository
    assert market_api.fx_quote_service._repository is not None


def test_historical_fx_endpoint_preserves_exact_date_and_knowledge_cutoff(monkeypatch):
    fake = FakeHistoricalFxService()
    monkeypatch.setattr(market_api, "fx_quote_service", fake)

    observed_on = date(2026, 8, 3)
    cutoff = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)

    response = market_api.get_historical_fx_quote(
        base_currency="USD",
        quote_currency="EUR",
        observed_on=observed_on,
        knowledge_cutoff=cutoff,
    )

    assert fake.calls == [
        {
            "base_currency": "USD",
            "quote_currency": "EUR",
            "observed_on": observed_on,
            "knowledge_cutoff": cutoff,
        }
    ]
    assert response["data"]["historicalPointInTimeEligible"] is True
    assert response["data"]["replayedFromPersistence"] is True
    assert response["data"]["sourceSymbol"] == "USDEUR=X"


def test_historical_fx_endpoint_allows_current_accounting_without_backdated_cutoff(monkeypatch):
    fake = FakeHistoricalFxService()
    monkeypatch.setattr(market_api, "fx_quote_service", fake)

    observed_on = date(2026, 8, 3)
    fake.get_historical_rate = lambda **kwargs: {
        "status": "fx_historical_ready",
        "baseCurrency": kwargs["base_currency"],
        "quoteCurrency": kwargs["quote_currency"],
        "rate": 0.92,
        "observedOn": kwargs["observed_on"].isoformat(),
        "historicalPointInTimeEligible": True,
        "replayedFromPersistence": False,
    }

    response = market_api.get_historical_fx_quote(
        base_currency="USD",
        quote_currency="EUR",
        observed_on=observed_on,
        knowledge_cutoff=None,
    )

    assert response["data"]["observedOn"] == "2026-08-03"
    assert response["data"]["historicalPointInTimeEligible"] is True


def test_historical_fx_endpoint_fails_closed_on_unverifiable_evidence(monkeypatch):
    class BrokenService:
        def get_historical_rate(self, **kwargs):
            raise RuntimeError("unverifiable")

    monkeypatch.setattr(market_api, "fx_quote_service", BrokenService())

    with pytest.raises(HTTPException) as exc_info:
        market_api.get_historical_fx_quote(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
            knowledge_cutoff=None,
        )

    assert exc_info.value.status_code == 502
    assert "histórica verificable" in exc_info.value.detail
