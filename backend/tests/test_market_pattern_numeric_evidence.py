"""Radar readiness must not coerce malformed provider bars into valid evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import market
from app.main import app


@pytest.mark.parametrize("field,bad_value", [
    ("close", True), ("close", "120.5"),
    ("volume", True), ("volume", "1000"),
])
def test_opportunity_readiness_rejects_coerced_numeric_evidence(
    monkeypatch, field, bad_value
) -> None:
    bar = {
        "symbol": "AAPL",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "close": 120.5,
        "volume": 1000,
        "low": 119.0,
        "sourceProvider": "yahoo",
    }
    bar[field] = bad_value
    monkeypatch.setattr(
        market.market_service, "get_history", lambda **_: [bar]
    )
    response = TestClient(app).get(
        "/api/v1/market/opportunity-pattern-readiness",
        params={"symbol": "AAPL"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["validDailySessions"] == 0
    assert data["invalidOrDuplicateRows"] == 1
    assert data["previous25SessionSignalEligible"] is False
    assert data["licenceVerified"] is False
    assert data["automaticTrading"] is False
