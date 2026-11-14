"""Current-provider chart history must never imply licensed PIT evidence."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import market
from app.main import app


def test_chart_history_reports_unverified_rights_and_pit(monkeypatch):
    observed = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    monkeypatch.setattr(
        market.market_service,
        "get_history",
        lambda **_: [{"symbol": "MSFT", "timestamp": observed,
                      "close": 100.0, "volume": 1234}],
    )
    response = TestClient(app).get("/api/v1/market/history", params={"symbol": "MSFT"})
    assert response.status_code == 200
    provenance = response.json()["provenance"]
    assert provenance["licenceVerified"] is False
    assert provenance["corporateActionsIndependentlyVerified"] is False
    assert provenance["historicalPointInTimeEligible"] is False
    assert provenance["historicalPointInTimeStatus"] == "not_verified"
    assert provenance["availableAt"] is None
    assert provenance["productionCoverageClaimed"] is False
    assert provenance["historyStatus"] == "available_unverified"
