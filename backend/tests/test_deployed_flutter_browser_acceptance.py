"""Configuration safety checks for the opt-in deployed browser runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "scripts" / "deployed_flutter_browser_acceptance.py"
spec = importlib.util.spec_from_file_location("deployed_flutter_browser_acceptance", PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SHA = "a" * 40


def config(**changes):
    env = {
        "GITHUB_SHA": SHA,
        "ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA": SHA,
        "ATHENA_ACCEPTANCE_WEB_URL": "https://staging.example.test/",
        "ATHENA_ACCEPTANCE_BASE_URL": "https://api.staging.example.test",
    }
    env.update(changes)
    return module.validate_config(env)


def test_exact_sha_and_https_origin():
    result = config()
    assert result.base_url == "https://staging.example.test/"
    assert result.deployed_sha == SHA
    assert result.backend_origin == "https://api.staging.example.test"


@pytest.mark.parametrize("url", [
    "http://staging.example.test", "https://user:password@staging.example.test",
    "https://staging.example.test/private", "https://staging.example.test/?token=x",
    "https://staging.example.test/#secret",
])
def test_unsafe_web_origins_fail_closed(url):
    with pytest.raises(module.BrowserAcceptanceFailure):
        config(ATHENA_ACCEPTANCE_WEB_URL=url)


@pytest.mark.parametrize("sha", ["", "b" * 40, "not-a-sha"])
def test_missing_or_mismatched_sha_fails_closed(sha):
    with pytest.raises(module.BrowserAcceptanceFailure):
        config(ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA=sha)


def test_missing_config_never_logs_secrets(monkeypatch, capsys):
    monkeypatch.delenv("ATHENA_ACCEPTANCE_WEB_URL", raising=False)
    monkeypatch.setenv("ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA", "secret-not-to-log")
    assert module.main() == 2
    assert "secret-not-to-log" not in capsys.readouterr().out


class _ManifestResponse:
    def __init__(self, payload, *, status=200, url="https://staging.example.test/athena-build.json"):
        self.payload = payload
        self.status = status
        self.url = url

    def json(self):
        return self.payload


class _ManifestPage:
    def __init__(self, response):
        self.request = self
        self.response = response
        self.requested_url = None
        self.headers = None

    def get(self, url, *, headers, timeout):
        self.requested_url = url
        self.headers = headers
        assert timeout == 15000
        return self.response


def _check_manifest(response):
    page = _ManifestPage(response)
    module.verify_deployed_web_build(
        page, expected_sha=SHA, expected_origin="https://staging.example.test/",
        expected_backend_origin="https://api.staging.example.test",
    )
    return page


def test_deployed_build_identity_uses_real_same_origin_manifest():
    page = _check_manifest(_ManifestResponse({
        "schema": "athena.web-build.v2", "sourceSha": SHA,
        "backendOrigin": "https://api.staging.example.test",
    }))
    assert page.requested_url.startswith("athena-build.json?")
    assert page.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("payload", [
    {},
    {"schema": "athena.web-build.v2", "sourceSha": "b" * 40},
    {"schema": "wrong", "sourceSha": SHA},
    {"schema": "athena.web-build.v2", "sourceSha": SHA, "extra": True},
    {"schema": "athena.web-build.v2", "sourceSha": SHA,
     "backendOrigin": "https://different-api.example.test"},
    {"schema": "athena.web-build.v2", "sourceSha": SHA,
     "backendOrigin": None},
    ["athena.web-build.v2", SHA],
])
def test_deployed_build_identity_rejects_wrong_or_ambiguous_manifest(payload):
    with pytest.raises(module.BrowserAcceptanceFailure):
        _check_manifest(_ManifestResponse(payload))


@pytest.mark.parametrize("status,url", [
    (404, "https://staging.example.test/athena-build.json"),
    (200, "https://other.example.test/athena-build.json"),
    (200, "http://staging.example.test/athena-build.json"),
    (200, "https://staging.example.test/other.json"),
])
def test_deployed_build_identity_rejects_missing_or_redirected_manifest(status, url):
    with pytest.raises(module.BrowserAcceptanceFailure):
        _check_manifest(_ManifestResponse({
            "schema": "athena.web-build.v2", "sourceSha": SHA,
            "backendOrigin": "https://api.staging.example.test",
        }, status=status, url=url))


@pytest.mark.parametrize("url,expected", [
    ("https://api.staging.example.test/api/v1/news/feed", True),
    ("https://api.staging.example.test:443/api/v1/news/feed?page=1", True),
    ("https://other.example.test/api/v1/news/feed", False),
    ("http://api.staging.example.test/api/v1/news/feed", False),
    ("https://api.staging.example.test:8443/api/v1/news/feed", False),
    ("https://api.staging.example.test/api/v1/news/feed/extra", False),
    ("https://user@api.staging.example.test/api/v1/news/feed", False),
    ("https://api.staging.example.test/api/v1/news/feed-malicious", False),
])
def test_live_http_evidence_requires_exact_https_backend_origin_and_path(url, expected):
    assert module._matches_backend_api(
        url, backend_origin="https://api.staging.example.test",
        path="/api/v1/news/feed",
    ) is expected


def test_news_refresh_rejects_untrusted_origin_even_when_real_requests_exist():
    with pytest.raises(module.BrowserAcceptanceFailure):
        module._require_news_refresh_requests([
            "/api/v1/recommendations/professional-research/news-synthesis/latest",
            "unexpected_origin",
        ], selective=True)


@pytest.mark.parametrize("selective,paths", [
    (True, ["/api/v1/recommendations/professional-research/news-synthesis/latest"]),
    (False, [
        "/api/v1/recommendations/professional-research/news-synthesis/latest",
        "/api/v1/news/feed",
    ]),
])
def test_news_refresh_requires_exact_network_scope(selective, paths):
    module._require_news_refresh_requests(paths, selective=selective)


@pytest.mark.parametrize("selective,paths", [
    (True, []),
    (True, ["/api/v1/news/feed",
            "/api/v1/recommendations/professional-research/news-synthesis/latest"]),
    (True, ["/api/v1/recommendations/professional-research/news-synthesis/latest"] * 2),
    (False, ["/api/v1/recommendations/professional-research/news-synthesis/latest"]),
    (False, ["/api/v1/news/feed"]),
])
def test_news_refresh_rejects_missing_extra_or_cross_surface_requests(selective, paths):
    with pytest.raises(module.BrowserAcceptanceFailure):
        module._require_news_refresh_requests(paths, selective=selective)


@pytest.mark.parametrize("url", [
    "", "http://api.staging.example.test", "https://localhost:8000",
    "https://127.0.0.1:8000", "https://user:pass@api.example.test",
    "https://api.example.test/private", "https://api.example.test?token=abc",
    "https://api.example.test/#fragment", "https://api.example.test:bad",
])
def test_unsafe_expected_backend_origin_fails_closed(url):
    with pytest.raises(module.BrowserAcceptanceFailure):
        config(ATHENA_ACCEPTANCE_BASE_URL=url)


class _CanonicalLiveResponse:
    def __init__(
        self, *, status=200,
        url="https://api.staging.example.test/api/v1/recommendations/professional-research/athena-synthesis/latest",
        content_type="application/json", payload=None,
    ):
        self.status = status
        self.url = url
        self.headers = {"content-type": content_type}
        self.payload = {"data": {"cycleBindingVerified": True}} if payload is None else payload

    def json(self):
        return self.payload


class _CanonicalLivePage:
    def __init__(self, response):
        self.request = self
        self.response = response

    def get(self, url, *, headers, max_redirects, timeout):
        assert url == (
            "https://api.staging.example.test"
            "/api/v1/recommendations/professional-research/athena-synthesis/latest"
        )
        assert headers["Cache-Control"] == "no-cache"
        assert max_redirects == 0
        assert timeout == 15000
        return self.response


def _live_canonical(response):
    return module._fetch_live_canonical_synthesis(
        _CanonicalLivePage(response),
        backend_origin="https://api.staging.example.test",
        path="/api/v1/recommendations/professional-research/athena-synthesis/latest",
    )


def test_delayed_success_requires_genuine_live_canonical_response():
    response = _CanonicalLiveResponse()
    assert _live_canonical(response) is response


@pytest.mark.parametrize("response", [
    _CanonicalLiveResponse(status=503),
    _CanonicalLiveResponse(url="https://untrusted.example.test/api/v1/recommendations/professional-research/athena-synthesis/latest"),
    _CanonicalLiveResponse(content_type="text/html"),
    _CanonicalLiveResponse(payload={"detail": "unavailable"}),
])
def test_delayed_success_rejects_unverified_or_noncanonical_response(response):
    with pytest.raises(module.BrowserAcceptanceFailure):
        _live_canonical(response)
