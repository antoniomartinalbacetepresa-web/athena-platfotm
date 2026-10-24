from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_NEW_PASSWORD = "NewCorrectHorseBatteryStaple!"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def test_recovery_reset_rate_limit_cannot_be_bypassed_by_rotating_tokens(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)

    for index in range(10):
        token = f"invalid-{index:02d}-" + ("x" * 32)
        response = client.post(
            "/api/v1/auth/recovery/reset",
            json={"token": token, "newPassword": _NEW_PASSWORD},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Token de recuperación no válido o caducado."

    blocked = client.post(
        "/api/v1/auth/recovery/reset",
        json={"token": "different-invalid-token-" + ("y" * 32), "newPassword": _NEW_PASSWORD},
    )

    assert blocked.status_code == 429, blocked.text
    assert blocked.headers["retry-after"] == "900"
    assert blocked.json()["detail"] == (
        "Demasiados intentos de restablecimiento. Inténtalo más tarde."
    )
