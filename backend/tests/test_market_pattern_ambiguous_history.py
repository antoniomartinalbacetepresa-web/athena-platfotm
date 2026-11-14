"""Provider ambiguity must not become a usable Radar reference session."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import market
from app.main import app


@pytest.mark.parametrize("malformed", [None, {"data": []}, "not-a-list"])
def test_readiness_rejects_malformed_provider_history(monkeypatch, malformed):
    monkeypatch.setattr(market.market_service, "get_history", lambda **_: malformed)
    response = TestClient(app).get(
        "/api/v1/market/opportunity-pattern-readiness",
        params={"symbol": "MSFT"},
    )
    assert response.status_code == 502


def test_readiness_excludes_ambiguous_duplicate_session(monkeypatch):
    start = datetime.now(timezone.utc) - timedelta(days=40)
    bars = [
        {
            "symbol": "MSFT",
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "close": 100.0,
            "low": 99.0,
            "volume": 1000,
            "sourceProvider": "unverified",
        }
        for day in range(26)
    ]
    duplicate = dict(bars[0], close=150.0, low=80.0)
    monkeypatch.setattr(
        market.market_service, "get_history", lambda **_: bars + [duplicate]
    )
    response = TestClient(app).get(
        "/api/v1/market/opportunity-pattern-readiness",
        params={"symbol": "MSFT"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["validDailySessions"] == 25
    assert data["invalidOrDuplicateRows"] == 1
    assert data["previous25SessionReferenceComplete"] is False
    assert data["previous25SessionLowDiagnostic"] is None
    assert data["licenceVerified"] is False
    assert data["automaticTrading"] is False
