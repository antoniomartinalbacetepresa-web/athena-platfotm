"""History charts reject ambiguous duplicate observations, including offset aliases."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import market
from app.main import app


@pytest.mark.parametrize("offset_hours", [0, 1])
def test_history_rejects_duplicate_instant(monkeypatch, offset_hours):
    instant = datetime.now(timezone.utc) - timedelta(days=2)
    rows = [
        {"symbol": "MSFT", "timestamp": instant.isoformat(), "close": 100.0, "volume": 1000},
        {
            "symbol": "MSFT",
            "timestamp": instant.astimezone(timezone(timedelta(hours=offset_hours))).isoformat(),
            "close": 101.0,
            "volume": 1100,
        },
    ]
    monkeypatch.setattr(market.market_service, "get_history", lambda **_: rows)
    response = TestClient(app).get("/api/v1/market/history", params={"symbol": "MSFT"})
    assert response.status_code == 502
    assert "duplicadas" in response.json()["detail"]
