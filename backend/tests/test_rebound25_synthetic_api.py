"""Authenticated synthetic strategy API; no market reads, writes or orders."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import rebound25_synthetic as api
from app.api.auth import current_account


URL = "/api/v1/research/strategies/rebound25/synthetic-backtest"


def synthetic_payload():
    first = datetime(2026, 1, 1, 14, tzinfo=timezone.utc)
    bars = [{
        "session": (first + timedelta(days=index)).date().isoformat(),
        "openAt": (first + timedelta(days=index)).isoformat(),
        "observedAt": (first + timedelta(days=index, hours=7)).isoformat(),
        "availableAt": (first + timedelta(days=index, hours=7, minutes=1)).isoformat(),
        "open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000,
    } for index in range(28)]
    bars[25].update(low=97, close=98, volume=2000)
    bars[26].update(open=98, high=100, low=97, close=99.5, volume=2000)
    bars[27].update(open=99.5, high=104, low=98, close=102, volume=1)
    return {
        "evidenceKind": "synthetic_fixture", "instrumentId": "SYNTH:XTEST", "currency": "USD",
        "asOf": bars[-1]["availableAt"], "precommittedAt": bars[0]["openAt"],
        "expectedSessions": [bar["session"] for bar in bars], "bars": bars,
        "parameters": {
            "takeProfitPct": 3, "stopLossPct": 2, "maxHoldingSessions": 5,
            "commissionBps": 5, "spreadBps": 10, "slippageBps": 5,
            "orderUnits": 10, "minAverageVolume": 100, "maxVolumeParticipation": .01,
            "minRelativeVolume": 1.5,
        },
    }


def client(*, authenticated=True):
    app = FastAPI()
    app.include_router(api.router)
    if authenticated:
        app.dependency_overrides[current_account] = lambda: {"id": 101}
    return TestClient(app)


def test_authentication_precedes_evaluation_even_for_malformed_requests(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("unauthenticated requests must never invoke the backtest")
    monkeypatch.setattr(api, "run_rebound25_synthetic_backtest", forbidden)
    for payload in (synthetic_payload(), {"evidenceKind": "real"}, None):
        response = client(authenticated=False).post(URL, json=payload)
        assert response.status_code == 401


def test_authenticated_synthetic_payload_is_reproducible_with_no_authority():
    payload = synthetic_payload()
    first = client().post(URL, json=payload)
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body == client().post(URL, json=payload).json()["data"]
    assert body["evidenceKind"] == "synthetic_fixture"
    assert body["closedTradeCount"] == 1
    assert body["parameters"]["lookback_sessions"] == 25
    assert body["parameters"]["min_rebound_pct"] == 1
    assert body["parameters"]["max_confirmation_sessions"] == 3
    assert body["totalNetPnl"] > 0  # A deterministic toy case, not a profitability claim.
    for key in ("productionEligible", "historicalPointInTimeEligible", "outOfSampleValidated",
                "automaticTrading", "ordersEnabled"):
        assert body[key] is False
    assert body["precommitBasis"] == "caller_declared_not_immutable_attestation"
    assert body["advisoryStatus"] == "no_advice"
    assert len(body["parameterFingerprint"]) == 64


@pytest.mark.parametrize("kind", ["real", "licensed", "unverified", True, None])
def test_non_synthetic_classification_is_rejected_before_evaluation(kind, monkeypatch):
    monkeypatch.setattr(api, "run_rebound25_synthetic_backtest",
                        lambda *_, **__: pytest.fail("invalid evidence must not be evaluated"))
    payload = synthetic_payload()
    payload["evidenceKind"] = kind
    assert client().post(URL, json=payload).status_code == 422


@pytest.mark.parametrize("location,field,value", [
    ("root", "ordersEnabled", True), ("parameters", "automaticTrading", True),
    ("bar", "historicalPointInTimeEligible", True),
    ("parameters", "maxHoldingSessions", True), ("parameters", "orderUnits", "10"),
    ("bar", "close", True), ("bar", "volume", "1000"),
    ("bar", "availableAt", "2026-01-01T21:01:00"),
    ("root", "asOf", "2026-01-27T21:01:00+01:99"),
])
def test_strict_extra_forbidden_contract_cannot_escalate_or_coerce(location, field, value):
    payload = synthetic_payload()
    target = (payload if location == "root" else payload["parameters"]
              if location == "parameters" else payload["bars"][0])
    target[field] = value
    assert client().post(URL, json=payload).status_code == 422


def test_bar_and_expected_session_counts_are_bounded_before_evaluation(monkeypatch):
    monkeypatch.setattr(api, "run_rebound25_synthetic_backtest",
                        lambda *_, **__: pytest.fail("oversized requests must not be evaluated"))
    payload = synthetic_payload()
    payload["bars"] = [deepcopy(payload["bars"][0]) for _ in range(5001)]
    assert client().post(URL, json=payload).status_code == 422
    payload = synthetic_payload()
    payload["expectedSessions"] = [payload["expectedSessions"][0]] * 5001
    assert client().post(URL, json=payload).status_code == 422


def test_semantic_pit_violation_is_rejected_without_promoting_precommit_claim():
    payload = synthetic_payload()
    payload["precommittedAt"] = payload["bars"][25]["availableAt"]
    response = client().post(URL, json=payload)
    assert response.status_code == 400
    assert "before the first evaluation" in response.json()["detail"]


def test_unexpected_failure_does_not_expose_provider_or_runtime_details(monkeypatch):
    def fail(*_, **__):
        raise RuntimeError("private-path-and-synthetic-secret")
    monkeypatch.setattr(api, "run_rebound25_synthetic_backtest", fail)
    response = client().post(URL, json=synthetic_payload())
    assert response.status_code == 503
    assert "synthetic-secret" not in response.text


def test_router_is_registered_in_the_application():
    from app.main import app
    # FastAPI may include routers lazily; exercise dispatch rather than its
    # private route-container representation. The registered route requires auth.
    assert TestClient(app).post(URL, json=synthetic_payload()).status_code == 401
