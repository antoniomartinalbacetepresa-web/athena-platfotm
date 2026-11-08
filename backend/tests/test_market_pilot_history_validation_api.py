"""Read-only pilot history API contract: synthetic records are not licensed evidence."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _payload():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    day = yesterday.date().isoformat()
    observed = yesterday.replace(hour=18, minute=0, second=0, microsecond=0)
    # A future 18:00 observation is avoided even when the test runs early UTC.
    observed = min(observed, datetime.now(timezone.utc) - timedelta(hours=2))
    available = observed + timedelta(minutes=1)
    retrieved = available + timedelta(minutes=1)
    return {
        "expectedSessions": [observed.date().isoformat()],
        "observations": [{
            "instrumentId": "MSFT", "source": "synthetic",
            "licenseRef": "unverified-test-only", "usageAuthorized": True,
            "observationAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "retrievedAt": retrieved.isoformat(),
            "currency": "USD", "isFinalBar": True,
            "open": 100.0, "high": 102.0, "low": 99.0,
            "close": 101.0, "volume": 100,
        }],
    }


def test_pilot_history_api_exposes_gaps_but_never_certifies_rights():
    payload = _payload()
    response = client.post("/api/v1/market/history/pilot-validation", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["coverageComplete"] is True
    assert body["data"]["operationallyVerified"] is False
    assert body["provenance"]["providerRightsIndependentlyVerified"] is False
    assert body["provenance"]["historicalPointInTimeEligible"] is False
    assert body["provenance"]["orderExecutionAllowed"] is False


def test_pilot_history_api_rejects_incomplete_bar():
    payload = _payload()
    payload["observations"][0].pop("volume")
    response = client.post("/api/v1/market/history/pilot-validation", json=payload)
    assert response.status_code == 422


def test_pilot_history_api_bounds_untrusted_input():
    payload = _payload()
    payload["expectedSessions"] = ["2026-01-01"] * 401
    response = client.post("/api/v1/market/history/pilot-validation", json=payload)
    assert response.status_code == 422
