from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import market as market_api
from app.main import app


class _GovernanceStub:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def get_approved_weights(self) -> dict[str, object]:
        return dict(self._payload)


class _FailingGovernanceStub:
    def get_approved_weights(self) -> dict[str, object]:
        raise RuntimeError("governance evidence unavailable")


def test_active_regional_weights_preserve_pending_human_approval(monkeypatch) -> None:
    payload = {
        "status": "blocked",
        "blockers": ["pending_human_approval"],
        "regionWeights": {},
        "proposalId": None,
        "humanApproved": False,
        "automaticApproval": False,
        "automaticTrading": False,
    }
    monkeypatch.setattr(
        market_api,
        "canonical_weighting_governance_service",
        _GovernanceStub(payload),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/market/universe/active-regional-weights")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == payload
    assert response.json()["data"]["regionWeights"] == {}
    assert response.json()["data"]["humanApproved"] is False
    assert response.json()["data"]["automaticApproval"] is False
    assert response.json()["data"]["automaticTrading"] is False


def test_active_regional_weights_return_only_governance_output(monkeypatch) -> None:
    payload = {
        "status": "approved",
        "blockers": [],
        "regionWeights": {"america": 0.5, "europe": 0.3, "asia": 0.2},
        "proposalId": 17,
        "humanApproved": True,
        "approvedBy": "human-reviewer",
        "automaticApproval": False,
        "automaticTrading": False,
    }
    monkeypatch.setattr(
        market_api,
        "canonical_weighting_governance_service",
        _GovernanceStub(payload),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/market/universe/active-regional-weights")

    assert response.status_code == 200, response.text
    assert response.json() == {"data": payload}


def test_active_regional_weights_fail_closed_when_governance_cannot_verify(monkeypatch) -> None:
    monkeypatch.setattr(
        market_api,
        "canonical_weighting_governance_service",
        _FailingGovernanceStub(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/market/universe/active-regional-weights")

    assert response.status_code == 500
    assert "gobernanza" in response.json()["detail"].lower()
