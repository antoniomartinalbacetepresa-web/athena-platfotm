from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"
_EMAIL = "privacy@example.com"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def test_access_token_does_not_duplicate_email_pii_and_me_resolves_identity_server_side(
    monkeypatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)

    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": _EMAIL,
            "password": _PASSWORD,
            "displayName": "Private User",
        },
    )
    assert created.status_code == 201, created.text

    login = client.post(
        "/api/v1/auth/token",
        data={"username": _EMAIL, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])

    # JWTs are signed but their payload is readable by the bearer. Direct identity
    # PII must therefore not be duplicated into claims that authorization does not need.
    claims = jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_exp": False,
            "verify_aud": False,
            "verify_iss": False,
        },
        algorithms=["HS256"],
    )
    assert "email" not in claims
    assert set(claims) == {"sub", "jti", "sv", "iat", "exp", "iss", "aud"}

    # Identity remains available through the authenticated server-side account lookup;
    # removing PII from the bearer credential must not remove legitimate profile data.
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["account"]["email"] == _EMAIL
    assert me.json()["account"]["displayName"] == "Private User"
