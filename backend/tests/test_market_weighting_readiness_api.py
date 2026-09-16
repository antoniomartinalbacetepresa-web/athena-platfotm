from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import market
from app.main import app


class FakeReadinessReport:
    def to_api_dict(self) -> dict[str, object]:
        return {
            "ready": False,
            "blockers": ["external_market_cap_validation_required"],
        }


class FakeReadinessService:
    def __init__(self) -> None:
        self.calls = 0

    def get_report(self) -> FakeReadinessReport:
        self.calls += 1
        return FakeReadinessReport()


def test_market_weighting_readiness_endpoint_is_read_only_diagnostic(monkeypatch) -> None:
    fake = FakeReadinessService()
    monkeypatch.setattr(market, "market_weighting_readiness_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/market/universe/weighting-readiness")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "ready": False,
            "blockers": ["external_market_cap_validation_required"],
        }
    }
    assert fake.calls == 1
