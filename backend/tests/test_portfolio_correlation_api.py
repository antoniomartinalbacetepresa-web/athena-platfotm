from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api import portfolio as portfolio_api


class FakeResult:
    def to_api_dict(self):
        return {
            "correlation": 0.42,
            "sampleCount": 12,
            "recommendationPolicy": "no_advice",
            "productionEligible": False,
            "allocationInfluence": False,
            "automaticTrading": False,
        }


class FakeService:
    calls = []

    def calculate_pair(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResult()


def test_portfolio_correlation_api_forwards_pit_contract(monkeypatch):
    FakeService.calls = []
    monkeypatch.setattr(portfolio_api, "PortfolioCorrelationService", FakeService)
    cutoff = datetime(2026, 9, 4, 19, tzinfo=timezone.utc)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    payload = portfolio_api.get_portfolio_pair_correlation(
        left_instrument_id=10,
        right_instrument_id=20,
        source_provider="yahoo_finance",
        knowledge_cutoff=cutoff,
        observed_from=start,
        observed_to=end,
    )

    assert payload["data"]["correlation"] == pytest.approx(0.42)
    assert payload["data"]["recommendationPolicy"] == "no_advice"
    assert payload["data"]["productionEligible"] is False
    assert FakeService.calls == [
        {
            "left_instrument_id": 10,
            "right_instrument_id": 20,
            "source_provider": "yahoo_finance",
            "knowledge_cutoff": cutoff,
            "observed_from": start,
            "observed_to": end,
        }
    ]


def test_portfolio_correlation_api_fails_closed_on_invalid_evidence(monkeypatch):
    class InvalidEvidenceService:
        def calculate_pair(self, **kwargs):
            raise ValueError("evidencia histórica insuficiente")

    monkeypatch.setattr(
        portfolio_api,
        "PortfolioCorrelationService",
        InvalidEvidenceService,
    )

    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.get_portfolio_pair_correlation(
            left_instrument_id=10,
            right_instrument_id=20,
            source_provider="yahoo_finance",
            knowledge_cutoff=datetime(2026, 9, 4, 19, tzinfo=timezone.utc),
            observed_from=None,
            observed_to=None,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "evidencia histórica insuficiente"


def test_portfolio_correlation_api_blocks_temporal_leakage(monkeypatch):
    class TemporalLeakService:
        def calculate_pair(self, **kwargs):
            raise RuntimeError("observación posterior al knowledge_cutoff")

    monkeypatch.setattr(
        portfolio_api,
        "PortfolioCorrelationService",
        TemporalLeakService,
    )

    with pytest.raises(HTTPException) as exc_info:
        portfolio_api.get_portfolio_pair_correlation(
            left_instrument_id=10,
            right_instrument_id=20,
            source_provider="yahoo_finance",
            knowledge_cutoff=datetime(2026, 9, 4, 19, tzinfo=timezone.utc),
            observed_from=None,
            observed_to=None,
        )

    assert exc_info.value.status_code == 409
