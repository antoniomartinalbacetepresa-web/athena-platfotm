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



class _BackendBuildResponse:
    def __init__(
        self, payload=None, *, status=200,
        url="https://api.staging.example.test/api/v1/build",
    ):
        self.status = status
        self.url = url
        self.payload = (
            {"schema": "athena.backend-build.v1", "sourceSha": SHA}
            if payload is None else payload
        )

    def json(self):
        return self.payload


class _BackendBuildPage:
    def __init__(self, response):
        self.request = self
        self.response = response

    def get(self, url, *, headers, max_redirects, timeout):
        assert url == "https://api.staging.example.test/api/v1/build"
        assert headers["Cache-Control"] == "no-cache"
        assert max_redirects == 0
        assert timeout == 15000
        return self.response


def _check_backend_build(response):
    module.verify_deployed_backend_build(
        _BackendBuildPage(response), expected_sha=SHA,
        backend_origin="https://api.staging.example.test",
    )


def test_deployed_browser_acceptance_requires_real_backend_sha():
    _check_backend_build(_BackendBuildResponse())


@pytest.mark.parametrize("response", [
    _BackendBuildResponse(status=503),
    _BackendBuildResponse(url="https://other.example.test/api/v1/build"),
    _BackendBuildResponse(url="http://api.staging.example.test/api/v1/build"),
    _BackendBuildResponse(payload={"schema": "athena.backend-build.v1", "sourceSha": "b" * 40}),
    _BackendBuildResponse(payload={"schema": "athena.backend-build.v1", "sourceSha": SHA, "extra": True}),
])
def test_deployed_browser_rejects_stale_or_untrusted_backend(response):
    with pytest.raises(module.BrowserAcceptanceFailure):
        _check_backend_build(response)


class _LiveSurfaceResponse:
    def __init__(self, path, data, *, status=200, origin="https://api.staging.example.test",
                 query="", selected=None, content_type="application/json"):
        self.status = status
        self.url = origin + path + query
        self.headers = {"content-type": content_type}
        self.payload = {"data": data}
        if selected is not None:
            self.payload["selectedFiling"] = selected

    def json(self):
        return self.payload


def _check_live_surface(response, path):
    module._require_live_surface_payload(
        response, backend_origin="https://api.staging.example.test", path=path
    )


def test_deployed_market_requires_nonempty_real_http_universe_and_status():
    universe = "/api/v1/market/universe"
    status = "/api/v1/market/universe/status"
    _check_live_surface(_LiveSurfaceResponse(universe, [{"symbol": "AAPL"}]), universe)
    _check_live_surface(
        _LiveSurfaceResponse(status, {"globallyUsableCount": 1, "activeCount": 1, "usingFallback": False}), status
    )
    for response, path in [
        (_LiveSurfaceResponse(universe, []), universe),
        (_LiveSurfaceResponse(universe, [{"symbol": ""}]), universe),
        (_LiveSurfaceResponse(status, {"globallyUsableCount": 0, "activeCount": 1, "usingFallback": False}), status),
        (_LiveSurfaceResponse(status, {"globallyUsableCount": True, "activeCount": 1, "usingFallback": False}), status),
        (_LiveSurfaceResponse(status, {"globallyUsableCount": 2, "activeCount": 1, "usingFallback": False}, status=503), status),
        (_LiveSurfaceResponse(universe, [{"symbol": "AAPL"}],
                              origin="https://untrusted.example.test"), universe),
    ]:
        with pytest.raises(module.BrowserAcceptanceFailure):
            _check_live_surface(response, path)


def test_deployed_sec_requires_live_cik_bound_passive_filing():
    path = "/api/v1/sec/institutional-holdings/latest"
    valid = {
        "sourceUrl": (
            "https://www.sec.gov/Archives/edgar/data/"
            "123456/000012345626000001/table.xml"
        ),
        "sourceProvider": "SEC EDGAR",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "automaticTrading": False,
        "holdings": [{"cusip": "037833100"}],
    }
    selected = {"accessionNumber": "0000123456-26-000001"}
    _check_live_surface(
        _LiveSurfaceResponse(path, valid, query="?cik=123456", selected=selected),
        path,
    )
    for changes, query in [
        ({}, "?cik=999999"),
        ({"sourceProvider": "unverified"}, "?cik=123456"),
        ({"automaticTrading": True}, "?cik=123456"),
        ({"holdings": []}, "?cik=123456"),
        ({}, ""),
    ]:
        with pytest.raises(module.BrowserAcceptanceFailure):
            _check_live_surface(
                _LiveSurfaceResponse(
                    path, {**valid, **changes}, query=query, selected=selected
                ), path,
            )


class _CanonicalResearchPage:
    def __init__(self, data):
        self.request = self
        self.data = data
        self.paths = []

    def get(self, url, *, headers, max_redirects, timeout):
        assert headers["Cache-Control"] == "no-cache"
        assert max_redirects == 0 and timeout == 15000
        self.paths.append(url)
        for suffix, data in self.data.items():
            if url.endswith(suffix):
                return _CanonicalLiveResponse(url=url, payload={"data": data})
        raise AssertionError("Unexpected canonical path")


def _research_data():
    cycle, pit, news_hash, investors_hash = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    return {
        "/athena-synthesis/latest": {
            "artifactBindingVerified": True, "cycleHash": cycle,
            "selection": {"presentationOnly": True, "recommendationInfluence": False,
                          "automaticTrading": False},
            "synthesis": {"inputFingerprint": pit},
            "provenance": {"inputFingerprint": pit,
                           "news": {"artifactHash": news_hash},
                           "investors": {"artifactHash": investors_hash}},
        },
        "/news-synthesis/latest": {
            "cycleBindingVerified": True, "cycleHash": cycle,
            "presentationOnly": True, "recommendationInfluence": False,
            "automaticTrading": False,
            "persistence": {"synthesisHash": news_hash},
        },
        f"/research-cycle/{cycle}/investors-synthesis": {
            "cycleBindingVerified": True, "cycleHash": cycle,
            "recommendationInfluence": False, "automaticTrading": False,
            "persistence": {"synthesisHash": investors_hash},
        },
    }


def test_deployed_browser_requires_live_canonical_three_surface_cycle():
    page = _CanonicalResearchPage(_research_data())
    assert module.verify_live_canonical_cycle(
        page, backend_origin="https://api.staging.example.test"
    ) == "a" * 64
    assert len(page.paths) == 3
    assert all(url.startswith("https://api.staging.example.test/api/v1/") for url in page.paths)


@pytest.mark.parametrize("surface,field,value", [
    ("news", "cycleHash", "f" * 64),
    ("news", "presentationOnly", False),
    ("news", "automaticTrading", True),
    ("investors", "cycleBindingVerified", False),
    ("investors", "recommendationInfluence", True),
    ("athena", "artifactBindingVerified", False),
    ("athena", "cycleHash", "not-a-sha"),
])
def test_deployed_browser_rejects_inconsistent_live_research(surface, field, value):
    data = _research_data()
    path = next(path for path in data if surface in path)
    data[path][field] = value
    with pytest.raises(module.BrowserAcceptanceFailure):
        module.verify_live_canonical_cycle(
            _CanonicalResearchPage(data),
            backend_origin="https://api.staging.example.test",
        )


def test_deployed_browser_rejects_pit_and_news_provenance_mismatch():
    data = _research_data()
    data["/athena-synthesis/latest"]["provenance"]["inputFingerprint"] = "f" * 64
    with pytest.raises(module.BrowserAcceptanceFailure):
        module.verify_live_canonical_cycle(
            _CanonicalResearchPage(data),
            backend_origin="https://api.staging.example.test",
        )
    data = _research_data()
    data["/athena-synthesis/latest"]["provenance"]["news"]["artifactHash"] = "f" * 64
    with pytest.raises(module.BrowserAcceptanceFailure):
        module.verify_live_canonical_cycle(
            _CanonicalResearchPage(data),
            backend_origin="https://api.staging.example.test",
        )


def test_deployed_market_status_rejects_fallback_even_when_counts_positive():
    path = "/api/v1/market/universe/status"
    for data in (
        {"globallyUsableCount": 1, "activeCount": 1, "usingFallback": True},
        {"globallyUsableCount": 1, "activeCount": 0, "usingFallback": False},
        {"globallyUsableCount": 1, "activeCount": True, "usingFallback": False},
    ):
        with pytest.raises(module.BrowserAcceptanceFailure):
            _check_live_surface(_LiveSurfaceResponse(path, data), path)


class _DelayedCanonicalResponse:
    def __init__(self, failure=None):
        self.failure = failure
        self.completed = False

    def finished(self):
        self.completed = True
        return self.failure


class _RenderAfterNetworkPage:
    def __init__(self, response):
        self.response = response
        self.rendered = False

    def evaluate(self, expression):
        assert self.response.completed
        assert expression.count("requestAnimationFrame") == 2
        self.rendered = True


def test_delayed_canonical_response_waits_for_network_and_render_frames():
    response = _DelayedCanonicalResponse()
    page = _RenderAfterNetworkPage(response)
    module._await_delayed_browser_response(page, response)
    assert response.completed is True
    assert page.rendered is True


def test_delayed_canonical_response_rejects_network_failure_before_render():
    response = _DelayedCanonicalResponse("failed")
    page = _RenderAfterNetworkPage(response)
    with pytest.raises(module.BrowserAcceptanceFailure, match="did not finish"):
        module._await_delayed_browser_response(page, response)
    assert response.completed is True
    assert page.rendered is False


def test_delayed_canonical_response_redacts_browser_failure():
    class BrokenPage:
        def evaluate(self, expression):
            raise RuntimeError("https://staging.example.test/?token=private")

    with pytest.raises(module.BrowserAcceptanceFailure) as error:
        module._await_delayed_browser_response(BrokenPage(), _DelayedCanonicalResponse())
    assert "private" not in str(error.value)
