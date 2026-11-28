from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
UTC = timezone.utc
AS_OF = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
ENDPOINT = "/api/v1/recommendations/professional-research/portfolio-state-reconciliation"


def _request(*, snapshot_currency: str = "EUR", snapshot_cash: float = 60.0) -> dict[str, object]:
    return {
        "asOf": AS_OF.isoformat(),
        "reconstructedState": {
            "portfolioStateKey": "a" * 64,
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "asOf": AS_OF.isoformat(),
            "cashBalance": 60.0,
            "positions": [
                {"instrumentId": "FIGI:AAA", "quantity": 2.0},
                {"instrumentId": "FIGI:BBB", "quantity": 3.0},
            ],
        },
        "snapshot": {
            "portfolioId": "portfolio-1",
            "reportingCurrency": snapshot_currency,
            "cashBalance": snapshot_cash,
            "positions": [
                {"instrumentId": "FIGI:AAA", "quantity": 2.0},
                {"instrumentId": "FIGI:BBB", "quantity": 3.0},
            ],
            "observedAt": (AS_OF - timedelta(minutes=10)).isoformat(),
            "availableAt": (AS_OF - timedelta(minutes=5)).isoformat(),
            "source": "broker_snapshot",
            "sourceRef": "snapshot-2026-09-08T1150Z",
        },
    }


def test_reconciliation_endpoint_is_registered_and_preserves_safety_contract() -> None:
    response = client.post(ENDPOINT, json=_request())

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["reconciled"] is True
    assert payload["cashDifference"] == 0.0
    assert payload["positionMismatches"] == []
    assert len(payload["reconciliationKey"]) == 64
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["cashInference"] == "forbidden"
    assert payload["policy"]["fxInference"] == "forbidden"


def test_reconciliation_endpoint_exposes_mismatch_without_silently_correcting_state() -> None:
    response = client.post(ENDPOINT, json=_request(snapshot_cash=61.25))

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["reconciled"] is False
    assert payload["cashDifference"] == 1.25
    assert payload["isWeightingReady"] is False


def test_reconciliation_endpoint_rejects_late_snapshot_for_no_lookahead() -> None:
    request = _request()
    request["snapshot"]["availableAt"] = (AS_OF + timedelta(seconds=1)).isoformat()

    response = client.post(ENDPOINT, json=request)

    assert response.status_code == 400
    assert "no estaba disponible" in response.json()["detail"]


def test_reconciliation_endpoint_rejects_currency_mismatch_without_explicit_fx() -> None:
    response = client.post(ENDPOINT, json=_request(snapshot_currency="USD"))

    assert response.status_code == 400
    assert "FX explícita" in response.json()["detail"]


def test_reconciliation_endpoint_rejects_timezone_naive_snapshot() -> None:
    request = _request()
    request["snapshot"]["observedAt"] = "2026-09-08T11:50:00"

    response = client.post(ENDPOINT, json=request)

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
