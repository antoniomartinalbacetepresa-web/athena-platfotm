from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def _register(monkeypatch, tmp_path: Path, *, email: str = "user@example.com") -> None:
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 201, response.text


def _login(*, email: str = "user@example.com", password: str = _PASSWORD):
    return client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )


def test_register_token_and_me_flow(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)

    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": "User@Example.com",
            "password": _PASSWORD,
            "displayName": "Athena User",
        },
    )
    assert created.status_code == 201
    account = created.json()["account"]
    assert account["email"] == "user@example.com"
    assert "password" not in account
    assert "password_hash" not in account

    token_response = _login()
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
    payload = {"email": "user@example.com", "password": _PASSWORD}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 400


def test_wrong_password_returns_generic_401(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)
    response = _login(password="WrongPassword123!")
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
        json={"email": "user@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Autenticación no configurada de forma segura."


def test_tampered_token_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)
    token = _login().json()["access_token"]

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


def test_logout_revokes_the_exact_access_token(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)
    first_token = _login().json()["access_token"]
    second_token = _login().json()["access_token"]
    assert first_token != second_token

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert logout.status_code == 204

    revoked = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert revoked.status_code == 401

    still_active = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert still_active.status_code == 200


def test_login_rate_limit_blocks_repeated_failures(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)

    for attempt in range(8):
        response = _login(password=f"WrongPassword-{attempt}-123!")
        assert response.status_code == 401, response.text

    blocked = _login(password="WrongPassword-9-123!")
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "300"
    assert "Demasiados intentos" in blocked.json()["detail"]


def test_successful_login_resets_rate_limit_counter(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)

    for attempt in range(7):
        assert _login(password=f"WrongPassword-{attempt}-123!").status_code == 401

    successful = _login()
    assert successful.status_code == 200

    # A successful authentication clears the persisted bucket, so failures may
    # start a new allowance rather than inheriting the previous seven attempts.
    assert _login(password="WrongPassword-after-success-123!").status_code == 401
