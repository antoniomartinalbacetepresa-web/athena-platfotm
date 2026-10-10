from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("ATHENA_AUTH_SECRET", "test-only-athena-auth-secret-32-bytes-minimum")

from app.main import app


client = TestClient(app)


def test_all_portfolio_routes_require_bearer_authentication() -> None:
    cases = [
        ("get", "/api/v1/portfolio/instrument-identity?symbol=AAPL", None),
        ("post", "/api/v1/portfolio/valuation-evidence", {}),
        (
            "get",
            "/api/v1/portfolio/correlation?leftInstrumentId=1&rightInstrumentId=2&sourceProvider=test&knowledgeCutoff=2026-01-01T00:00:00Z",
            None,
        ),
        ("post", "/api/v1/portfolio/correlation-evidence", {}),
        ("post", "/api/v1/portfolio/allocation-candidate", {}),
    ]

    for method, url, payload in cases:
        response = client.request(method.upper(), url, json=payload)
        assert response.status_code == 401, (method, url, response.status_code, response.text)
        assert response.headers.get("www-authenticate") == "Bearer"


def test_invalid_bearer_token_is_rejected_before_portfolio_processing() -> None:
    response = client.get(
        "/api/v1/portfolio/instrument-identity?symbol=AAPL",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales no válidas."
