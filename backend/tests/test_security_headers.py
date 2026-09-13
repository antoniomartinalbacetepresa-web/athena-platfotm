from fastapi.testclient import TestClient

from app.main import app


_EXPECTED_COMMON_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def _assert_common_security_headers(response) -> None:
    for name, expected in _EXPECTED_COMMON_HEADERS.items():
        assert response.headers[name] == expected


def test_http_health_has_defensive_headers_without_hsts() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/health")

    assert response.status_code == 200
    _assert_common_security_headers(response)
    assert "strict-transport-security" not in response.headers


def test_https_responses_include_hsts_even_for_handled_errors() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    _assert_common_security_headers(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_cors_preflight_keeps_security_headers() -> None:
    origin = "http://localhost:5173"
    with TestClient(app, base_url="http://testserver") as client:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    _assert_common_security_headers(response)
    assert response.headers["access-control-allow-origin"] == origin
    assert "strict-transport-security" not in response.headers


def test_api_documentation_remains_available_outside_production(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_ENV", raising=False)

    with TestClient(app, base_url="http://testserver") as client:
        docs = client.get("/docs")
        schema = client.get("/openapi.json")

    assert docs.status_code == 200
    assert schema.status_code == 200
    _assert_common_security_headers(docs)
    _assert_common_security_headers(schema)


def test_production_hides_docs_redoc_and_openapi_with_generic_404(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_ENV", "production")

    with TestClient(app, base_url="https://testserver") as client:
        responses = [client.get(path) for path in ("/docs", "/redoc", "/openapi.json")]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
        _assert_common_security_headers(response)
        assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_production_docs_guard_does_not_hide_application_routes(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_ENV", "prod")

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    _assert_common_security_headers(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"
