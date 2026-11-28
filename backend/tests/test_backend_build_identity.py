"""Runtime build identity must fail closed unless deployment sets an exact SHA."""

from fastapi.testclient import TestClient

from app.main import app


def test_deployed_backend_exposes_exact_non_secret_sha(monkeypatch):
    sha = "a" * 40
    monkeypatch.setenv("ATHENA_DEPLOYED_SOURCE_SHA", sha)
    with TestClient(app) as client:
        response = client.get("/api/v1/build")
    assert response.status_code == 200
    assert response.json() == {
        "schema": "athena.backend-build.v1", "sourceSha": sha,
    }
    assert response.headers["cache-control"] == "no-store"


def test_missing_or_invalid_deployment_sha_never_claims_identity(monkeypatch):
    for value in ("", "a" * 39, "A" * 40, "not-a-sha", "a" * 40 + "\n"):
        monkeypatch.setenv("ATHENA_DEPLOYED_SOURCE_SHA", value)
        with TestClient(app) as client:
            response = client.get("/api/v1/build")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "sourceSha" not in response.text
