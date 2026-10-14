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


def _assert_sensitive_response_is_not_cacheable(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_http_health_has_defensive_headers_without_hsts() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/health")

    assert response.status_code == 200
    _assert_common_security_headers(response)
    assert "strict-transport-security" not in response.headers
    assert "cache-control" not in response.headers
    assert "pragma" not in response.headers


def test_https_responses_include_hsts_even_for_handled_errors() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    _assert_common_security_headers(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_sensitive_auth_responses_are_no_store_even_on_validation_errors() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/v1/auth/token", data={})

    assert response.status_code == 422
    _assert_common_security_headers(response)
    _assert_sensitive_response_is_not_cacheable(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_sensitive_user_responses_are_no_store_even_when_unauthorized() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/v1/user/profile/preferences")

    assert response.status_code == 401
    _assert_common_security_headers(response)
    _assert_sensitive_response_is_not_cacheable(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_authenticated_portfolio_namespace_is_never_cacheable() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/v1/portfolio/valuation-evidence")

    # The route currently rejects GET with 405 before authentication. The cache
    # policy belongs to the sensitive namespace itself, so method rejection must
    # be protected exactly like auth/validation failures.
    assert response.status_code in {401, 403, 404, 405, 422}
    _assert_common_security_headers(response)
    _assert_sensitive_response_is_not_cacheable(response)
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_similarly_named_portfolio_path_is_not_misclassified_as_sensitive() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/api/v1/portfolios")

    assert response.status_code == 404
    _assert_common_security_headers(response)
    assert "cache-control" not in response.headers
    assert "pragma" not in response.headers


def test_similarly_named_public_path_is_not_misclassified_as_sensitive() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/api/v1/authors")

    assert response.status_code == 404
    _assert_common_security_headers(response)
    assert "cache-control" not in response.headers
    assert "pragma" not in response.headers


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
