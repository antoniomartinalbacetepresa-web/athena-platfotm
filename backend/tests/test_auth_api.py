from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def test_register_token_and_me_flow(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)

    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": "User@Example.com",
            "password": "CorrectHorseBatteryStaple!",
            "displayName": "Athena User",
        },
    )
    assert created.status_code == 201
    account = created.json()["account"]
    assert account["email"] == "user@example.com"
    assert "password" not in account
    assert "password_hash" not in account

    token_response = client.post(
        "/api/v1/auth/token",
        data={
            "username": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]
    assert token_response.json()["token_type"] == "bearer"

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["account"]["email"] == "user@example.com"


def test_duplicate_email_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    payload = {
        "email": "user@example.com",
        "password": "CorrectHorseBatteryStaple!",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 400


def test_wrong_password_returns_generic_401(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )

    response = client.post(
        "/api/v1/auth/token",
        data={"username": "user@example.com", "password": "WrongPassword123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales no válidas."


def test_short_password_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_auth_refuses_to_run_without_secure_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.delenv("ATHENA_AUTH_SECRET", raising=False)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Autenticación no configurada de forma segura."


def test_tampered_token_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )
    token = client.post(
        "/api/v1/auth/token",
        data={
            "username": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    ).json()["access_token"]

    # Mutate the first Base64URL character of the signature. Mutating the last
    # character is not reliable because unused padding bits can yield the same
    # decoded signature bytes for multiple textual encodings.
    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"
    assert tampered != token

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert response.status_code == 401
