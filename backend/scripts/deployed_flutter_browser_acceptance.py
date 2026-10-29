"""Opt-in deployed Flutter Web guest browser journey (never production approval).

Uses the real deployed web bundle and live canonical API responses. The 503
fault is browser-injected only, and is never represented as a provider outage.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class BrowserAcceptanceFailure(RuntimeError):
    """Safe failure; never log a browser exception or a staging URL."""


@dataclass(frozen=True)
class BrowserConfig:
    base_url: str
    deployed_sha: str
    backend_origin: str


def validate_config(environment: dict[str, str]) -> BrowserConfig:
    base = environment.get("ATHENA_ACCEPTANCE_WEB_URL", "").strip()
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or any(c.isspace() for c in base)
    ):
        raise BrowserAcceptanceFailure("HTTPS web origin required")
    expected = environment.get("GITHUB_SHA", "").strip().lower()
    deployed = environment.get("ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or deployed != expected:
        raise BrowserAcceptanceFailure("Exact deployed web SHA attestation required")
    backend = environment.get("ATHENA_ACCEPTANCE_BASE_URL", "")
    try:
        parsed_backend = urlsplit(backend)
        if (
            not backend or backend != backend.strip()
            or any(c.isspace() or ord(c) < 32 for c in backend)
            or "\\" in backend
            or parsed_backend.scheme != "https" or not parsed_backend.hostname
            or parsed_backend.username is not None or parsed_backend.password is not None
            or parsed_backend.path not in ("", "/")
            or parsed_backend.query or parsed_backend.fragment
            or parsed_backend.hostname.lower() in ("localhost", "127.0.0.1", "::1")
        ):
            raise ValueError("invalid backend origin")
        _ = parsed_backend.port
    except ValueError:
        raise BrowserAcceptanceFailure("Public HTTPS backend origin required") from None
    return BrowserConfig(
        base_url=base.rstrip("/") + "/", deployed_sha=deployed,
        backend_origin=backend.rstrip("/"),
    )


def verify_deployed_web_build(page, *, expected_sha: str, expected_origin: str,
                              expected_backend_origin: str) -> None:
    """Read the actual deployed bundle marker, not only the operator's SHA variable.

    This is a same-origin build identity check, not a signed deployment attestation.
    """
    try:
        response = page.request.get(
            "athena-build.json?athena_acceptance_sha=" + expected_sha,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=15000,
        )
        location = urlsplit(response.url)
        origin = urlsplit(expected_origin)
        if (
            response.status != 200
            or location.scheme != "https"
            or location.netloc != origin.netloc
            or location.path != "/athena-build.json"
        ):
            raise BrowserAcceptanceFailure("Deployed web build identity unavailable")
        manifest = response.json()
    except Exception:
        # Transport and parsing exceptions can contain staging URLs.
        raise BrowserAcceptanceFailure("Deployed web build identity unavailable") from None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "sourceSha", "backendOrigin"}
        or manifest.get("schema") != "athena.web-build.v2"
        or manifest.get("sourceSha") != expected_sha
        or manifest.get("backendOrigin") != expected_backend_origin
    ):
        raise BrowserAcceptanceFailure("Deployed web build SHA mismatch")


def _matches_backend_api(url: str, *, backend_origin: str, path: str) -> bool:
    """Only responses from the configured HTTPS backend count as live evidence."""
    try:
        actual = urlsplit(url)
        expected = urlsplit(backend_origin)
        return (
            actual.scheme == "https"
            and actual.hostname == expected.hostname
            and (actual.port or 443) == (expected.port or 443)
            and actual.username is None and actual.password is None
            and actual.path == path
        )
    except ValueError:
        return False


def _heading(page, label: str) -> None:
    page.get_by_role("heading", name=label, exact=True).first.wait_for(
        state="visible", timeout=30000
    )


def _back(page) -> None:
    page.get_by_role(
        "button", name=re.compile(r"^(Back|Volver|Atrás)$", re.IGNORECASE)
    ).first.click(timeout=15000)


def _visit(page, button: str, heading: str) -> None:
    page.get_by_role("button", name=button, exact=True).click(timeout=15000)
    _heading(page, heading)


def _require_news_refresh_requests(paths: list[str], *, selective: bool) -> None:
    """Require the intended live endpoints, never an unrelated cached response."""
    synthesis = "/api/v1/recommendations/professional-research/news-synthesis/latest"
    feed = "/api/v1/news/feed"
    expected = {synthesis: 1, feed: 0 if selective else 1}
    if any(path not in expected for path in paths) or any(
        paths.count(path) != count for path, count in expected.items()
    ):
        raise BrowserAcceptanceFailure("News refresh request scope mismatch")


def verify_news_refresh_scope(page, *, backend_origin: str) -> None:
    """Exercise independent News synthesis refresh and full News refresh in staging.

    Network requests are observed, not mocked. The existing Flutter UI must
    render canonical synthesis after both refreshes. This is not a claim that
    the underlying news provider is available outside this staging run.
    """
    synthesis = "/api/v1/recommendations/professional-research/news-synthesis/latest"
    feed = "/api/v1/news/feed"
    page.get_by_text(
        re.compile(r"artículos ·|Sin noticias verificadas|Noticias no disponibles")
    ).first.wait_for(state="visible", timeout=30000)
    requested: list[str] = []

    def record(request) -> None:
        path = urlsplit(request.url).path
        if path in (synthesis, feed):
            requested.append(
                path if _matches_backend_api(
                    request.url, backend_origin=backend_origin, path=path
                ) else "unexpected_origin"
            )

    page.on("request", record)
    try:
        with page.expect_response(
            lambda response: _matches_backend_api(
                response.url, backend_origin=backend_origin, path=synthesis
            ),
            timeout=30000,
        ) as synthesis_response:
            page.get_by_role(
                "button", name="Actualizar análisis ATHENA de noticias", exact=True
            ).click(timeout=15000)
        if synthesis_response.value.status != 200:
            raise BrowserAcceptanceFailure("News selective refresh unavailable")
        _heading(page, "ANÁLISIS ATHENA DE NOTICIAS")
        _require_news_refresh_requests(requested, selective=True)

        requested.clear()
        with page.expect_response(
            lambda response: _matches_backend_api(
                response.url, backend_origin=backend_origin, path=synthesis
            ),
            timeout=30000,
        ) as synthesis_response, page.expect_response(
            lambda response: _matches_backend_api(
                response.url, backend_origin=backend_origin, path=feed
            ),
            timeout=30000,
        ) as feed_response:
            page.get_by_role(
                "button", name="Actualizar noticias y análisis ATHENA", exact=True
            ).click(timeout=15000)
        if synthesis_response.value.status != 200 or feed_response.value.status != 200:
            raise BrowserAcceptanceFailure("News full refresh unavailable")
        _heading(page, "ANÁLISIS ATHENA DE NOTICIAS")
        _require_news_refresh_requests(requested, selective=False)
    finally:
        page.remove_listener("request", record)



def _fetch_live_canonical_synthesis(page, *, backend_origin: str, path: str):
    """Capture a genuine canonical 200 for a controlled delayed-reply race."""
    try:
        response = page.request.get(
            backend_origin + path,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            max_redirects=0, timeout=15000,
        )
        if (
            response.status != 200
            or not _matches_backend_api(
                response.url, backend_origin=backend_origin, path=path
            )
            or "application/json" not in response.headers.get(
                "content-type", ""
            ).lower()
            or not isinstance(response.json().get("data"), dict)
        ):
            raise BrowserAcceptanceFailure("Live canonical synthesis unavailable")
        return response
    except Exception:
        # Exceptions may include staging URLs. Never expose them.
        raise BrowserAcceptanceFailure("Live canonical synthesis unavailable") from None


def verify_stale_synthesis_ordering(page, *, backend_origin: str) -> None:
    """A delayed genuine 200 must not override a newer browser-injected 503."""
    path = "/api/v1/recommendations/professional-research/athena-synthesis/latest"
    live_response = _fetch_live_canonical_synthesis(
        page, backend_origin=backend_origin, path=path
    )
    held_routes = []
    requests_seen = 0
    released = False

    def matches(url: str) -> bool:
        return _matches_backend_api(url, backend_origin=backend_origin, path=path)

    def intercept(route) -> None:
        nonlocal requests_seen
        requests_seen += 1
        if requests_seen == 1:
            held_routes.append(route)
        else:
            route.fulfill(
                status=503, content_type="application/json",
                body='{"detail":"controlled acceptance fault"}',
            )

    page.route(matches, intercept)
    try:
        refresh = page.get_by_role(
            "button", name="Actualizar síntesis ATHENA verificada", exact=True
        )
        refresh.click(timeout=15000)
        for _ in range(50):
            if held_routes:
                break
            page.wait_for_timeout(100)
        if len(held_routes) != 1 or requests_seen != 1:
            raise BrowserAcceptanceFailure("Delayed canonical request not observed")
        with page.expect_response(
            lambda response: response.status == 503 and matches(response.url),
            timeout=30000,
        ):
            refresh.click(timeout=15000)
        page.get_by_text(
            "No se pudo verificar la síntesis ATHENA.", exact=True
        ).wait_for(state="visible", timeout=30000)
        if page.get_by_text("Fuentes verificadas", exact=True).count():
            raise BrowserAcceptanceFailure("Newer failure retained stale provenance")
        if requests_seen != 2:
            raise BrowserAcceptanceFailure("Unexpected canonical refresh requests")

        held_routes[0].fulfill(response=live_response)
        released = True
        page.wait_for_timeout(600)
        page.get_by_text(
            "No se pudo verificar la síntesis ATHENA.", exact=True
        ).wait_for(state="visible", timeout=1500)
        if page.get_by_text("Fuentes verificadas", exact=True).count():
            raise BrowserAcceptanceFailure("Delayed success overrode newer failure")
    finally:
        if held_routes and not released:
            try:
                held_routes[0].abort()
            except Exception:
                pass
        page.unroute(matches, intercept)

    with page.expect_response(
        lambda response: response.status == 200 and matches(response.url),
        timeout=30000,
    ):
        page.get_by_role("button", name="Reintentar", exact=True).click()
    page.get_by_text("Fuentes verificadas", exact=True).wait_for(
        state="visible", timeout=30000
    )


def verify_guest_research(page, *, backend_origin: str) -> dict[str, bool]:
    """Check real deployed navigation and explicitly scoped fault recovery."""
    seen: set[str] = set()

    def record(response) -> None:
        if response.status != 200:
            return
        for label, path in (
            ("athena", "/api/v1/recommendations/professional-research/athena-synthesis/latest"),
            ("news", "/api/v1/recommendations/professional-research/news-synthesis/latest"),
        ):
            if _matches_backend_api(
                response.url, backend_origin=backend_origin, path=path
            ):
                seen.add(label)

    page.on("response", record)
    page.goto("/", wait_until="domcontentloaded", timeout=45000)
    placeholder = page.locator("flt-semantics-placeholder")
    try:
        placeholder.first.wait_for(state="visible", timeout=12000)
    except Exception:
        pass  # Some Flutter builds already expose semantics.
    else:
        placeholder.first.click()
    page.get_by_role("button", name="Continuar como invitado").click(timeout=30000)
    page.get_by_role("button", name="Mercado", exact=True).wait_for(
        state="visible", timeout=30000
    )

    _visit(page, "Mercado", "MERCADO")
    _heading(page, "MERCADO GLOBAL")
    _back(page)
    _visit(page, "Noticias", "NOTICIAS")
    _heading(page, "ANÁLISIS ATHENA DE NOTICIAS")
    verify_news_refresh_scope(page, backend_origin=backend_origin)
    _back(page)
    _visit(page, "Inversores", "INVERSORES")
    _heading(page, "ACTIVIDAD DE INVERSORES RELEVANTES")
    page.get_by_text(re.compile(r"CIK \d+")).first.wait_for(
        state="visible", timeout=30000
    )
    _back(page)
    _visit(page, "ATHENA AI", "ATHENA AI")
    page.get_by_text("Fuentes verificadas", exact=True).wait_for(
        state="visible", timeout=30000
    )
    if not {"athena", "news"}.issubset(seen):
        raise BrowserAcceptanceFailure("Live canonical responses missing")

    # Inject one controlled browser-side fault; never fabricate success data.
    synthesis_path = "/api/v1/recommendations/professional-research/athena-synthesis/latest"
    def matches_synthesis(url: str) -> bool:
        return _matches_backend_api(
            url, backend_origin=backend_origin, path=synthesis_path
        )

    def reject(route) -> None:
        route.fulfill(
            status=503, content_type="application/json",
            body='{"detail":"controlled acceptance fault"}',
        )

    page.route(matches_synthesis, reject)
    try:
        page.get_by_role(
            "button", name="Actualizar síntesis ATHENA verificada"
        ).click()
        page.get_by_text(
            "No se pudo verificar la síntesis ATHENA.", exact=True
        ).wait_for(state="visible", timeout=30000)
        if page.get_by_text("Fuentes verificadas", exact=True).count():
            raise BrowserAcceptanceFailure("Stale provenance remained visible")
    finally:
        page.unroute(matches_synthesis, reject)
    with page.expect_response(
        lambda response: response.status == 200 and _matches_backend_api(
            response.url, backend_origin=backend_origin, path=synthesis_path
        ), timeout=30000,
    ):
        page.get_by_role("button", name="Reintentar", exact=True).click()
    page.get_by_text("Fuentes verificadas", exact=True).wait_for(
        state="visible", timeout=30000
    )
    verify_stale_synthesis_ordering(page, backend_origin=backend_origin)
    _back(page)

    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Navegación").click()
    page.get_by_text("Mercado", exact=True).last.click()
    _heading(page, "MERCADO")
    _back(page)
    return {
        "liveCanonicalHttpObserved": True,
        "guestNavigationWideAndCompactVerified": True,
        "verifiedProvenanceVisible": True,
        "controlledFaultRecoveryVerified": True,
        "newsSelectiveAndFullRefreshVerified": True,
    }


def main() -> int:
    try:
        config = validate_config(dict(os.environ))
    except (BrowserAcceptanceFailure, ValueError):
        print(json.dumps({
            "status": "blocked", "reason": "Staging web origin or exact SHA attestation missing",
        }))
        return 2
    stage = "browser"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    base_url=config.base_url,
                    viewport={"width": 1440, "height": 900},
                    service_workers="block",
                )
                page = context.new_page()
                stage = "deployed-web-build-identity"
                verify_deployed_web_build(
                    page, expected_sha=config.deployed_sha,
                    expected_origin=config.base_url,
                    expected_backend_origin=config.backend_origin,
                )
                stage = "guest-research"
                result = verify_guest_research(
                    page, backend_origin=config.backend_origin
                )
                context.close()
            finally:
                browser.close()
    except Exception:
        # Browser exceptions may embed URLs, headers or sensitive page data.
        print(json.dumps({
            "status": "failed", "stage": stage, "reason": "Browser acceptance did not pass",
        }))
        return 3
    print(json.dumps({
        "status": "passed", **result,
        "deployedFlutterGuestResearchVerified": True,
        "deployedWebBuildIdentityVerified": True,
        "deployedFlutterBrowserE2EVerified": False,
        "twoOwnerBrowserIsolationVerified": False,
        "staleResponseOrderingVerified": True,
        "selectiveRefreshVerified": True,
        "productionAuthorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
