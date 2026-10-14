from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.security.portfolio_owner_storage import owner_scoped_ledger_path


AUTH_SECRET = "athena-ledger-cleanup-test-secret-0123456789abcdef"
PASSWORD = "CorrectHorseBatteryStaple!"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_close_account_purges_only_authenticated_owner_ledger(monkeypatch, tmp_path) -> None:
    """Local E2E acceptance only; this fixture is not production evidence."""
    base_ledger = tmp_path / "portfolio_event_ledger.jsonl"
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(base_ledger))

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/register",
            json={"email": "ledger-cleanup@example.com", "password": PASSWORD},
        )
        assert created.status_code == 201, created.text
        owner_id = int(created.json()["account"]["id"])

        login = client.post(
            "/api/v1/auth/token",
            data={"username": "ledger-cleanup@example.com", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        token = str(login.json()["access_token"])

        owner_ledger = owner_scoped_ledger_path(base_ledger, owner_user_id=owner_id)
        other_ledger = owner_scoped_ledger_path(base_ledger, owner_user_id=owner_id + 1000)
        owner_ledger.parent.mkdir(parents=True)
        other_ledger.parent.mkdir(parents=True)
        owner_ledger.write_text("owner-history\n", encoding="utf-8")
        other_ledger.write_text("other-history\n", encoding="utf-8")

        closed = client.post(
            "/api/v1/auth/close-account",
            headers=_headers(token),
            json={"currentPassword": PASSWORD},
        )
        assert closed.status_code == 204, closed.text
        assert not owner_ledger.exists()
        assert other_ledger.read_text(encoding="utf-8") == "other-history\n"
        assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401
