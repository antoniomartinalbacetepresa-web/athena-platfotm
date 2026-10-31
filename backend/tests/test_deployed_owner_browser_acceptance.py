"""Guard regressions for the opt-in deployed two-owner browser acceptance.

These are not deployed E2E evidence; the staging browser job supplies that.
"""
from types import SimpleNamespace

import httpx
import pytest

from scripts.deployed_flutter_browser_acceptance import BrowserAcceptanceFailure
from scripts.deployed_owner_browser_acceptance import BrowserAuthorityObserver, _revoked


BACKEND = "https://staging-api.example.test"


def request(url: str, authorization: str):
    return SimpleNamespace(url=url, headers={"authorization": authorization})


def test_browser_authority_requires_exact_backend_and_single_bearer():
    observer = BrowserAuthorityObserver(BACKEND)
    observer.observe(request(BACKEND + "/api/v1/auth/me", "Bearer test-owner-a"))
    assert observer.token() == "test-owner-a"
    observer.observe(request(BACKEND + "/api/v1/user/portfolio", "Bearer test-owner-b"))
    with pytest.raises(BrowserAcceptanceFailure):
        observer.token()


def test_browser_authority_rejects_lookalike_origin_without_leaking_token():
    observer = BrowserAuthorityObserver(BACKEND)
    observer.observe(request(BACKEND + "/api/v1/auth/me", "Bearer test-owner-a"))
    observer.observe(request(
        "https://staging-api.example.test.evil.invalid/api/v1/auth/me", "Bearer test-owner-a"
    ))
    with pytest.raises(BrowserAcceptanceFailure, match="authority"):
        observer.token()


def test_revocation_checks_every_protected_surface():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer disposable-token"
        return httpx.Response(401)

    with httpx.Client(base_url=BACKEND, transport=httpx.MockTransport(handler)) as client:
        _revoked(client, "disposable-token")
    assert paths == [
        "/api/v1/auth/me", "/api/v1/user/profile/preferences",
        "/api/v1/user/profile/personalization", "/api/v1/user/portfolio",
    ]


def test_revocation_fails_closed_on_one_still_authorized_surface():
    def handler(request):
        return httpx.Response(200 if request.url.path.endswith("/portfolio") else 401)

    with httpx.Client(base_url=BACKEND, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BrowserAcceptanceFailure, match="Revoked"):
            _revoked(client, "disposable-token")
