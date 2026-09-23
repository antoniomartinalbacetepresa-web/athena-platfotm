from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app
from app.security.portfolio_owner_storage import owner_scoped_ledger_path


def test_account_closure_purges_owner_dividend_history(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "closure-ledger.db"
    ledger_path = tmp_path / "portfolio-ledger.jsonl"
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", "x" * 64)
    monkeypatch.setenv(
        "ATHENA_PROFILE_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
    )
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(ledger_path))

    email = "closure-ledger@example.com"
    password = "CorrectHorseBatteryStaple!"
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert created.status_code == 201, created.text
        owner_id = int(created.json()["account"]["id"])
        login = client.post(
            "/api/v1/auth/token",
            data={"username": email, "password": password},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        dividend = client.post(
            "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
            headers=headers,
            json={
                "portfolioId": "personal",
                "eventType": "cash_dividend",
                "occurredAt": "2026-09-22T10:00:00Z",
                "availableAt": "2026-09-22T12:00:00Z",
                "currency": "EUR",
                "amount": 2.75,
                "instrumentId": "AAPL:XNAS",
                "quantity": None,
                "source": "issuer_filing",
                "sourceRef": "closure-dividend-q3",
                "asOf": "2026-09-23T00:00:00Z",
            },
        )
        assert dividend.status_code == 200, dividend.text
        assert dividend.json()["data"]["policy"]["automaticTrading"] is False

        history = client.get(
            "/api/v1/user/portfolio/history",
            headers=headers,
            params={"portfolioId": "personal", "asOf": "2026-09-23T00:00:00Z"},
        )
        assert history.status_code == 200, history.text
        events = history.json()["data"]["events"]
        assert len(events) == 1
        assert events[0]["eventType"] == "cash_dividend"
        assert events[0]["source"] == "issuer_filing"
        assert events[0]["sourceRef"] == "closure-dividend-q3"

        physical_ledger = owner_scoped_ledger_path(ledger_path, owner_user_id=owner_id)
        assert physical_ledger.exists()
        closed = client.post(
            "/api/v1/auth/close-account",
            headers=headers,
            json={"currentPassword": password},
        )
        assert closed.status_code == 204, closed.text
        assert not physical_ledger.exists()
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
