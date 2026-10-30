"""Opt-in deployed Flutter Web guest browser journey (never production approval).

Uses the real deployed web bundle and live canonical API responses. The 503
fault is browser-injected only, and is never represented as a provider outage.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


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


def verify_deployed_backend_build(page, *, expected_sha: str, backend_origin: str) -> None:
    """Require the actual staging API to report the same source SHA as Web.

    A runtime SHA marker is deployment-configured, not signed provenance.
    """
    path = "/api/v1/build"
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
        ):
            raise BrowserAcceptanceFailure("Deployed backend build identity unavailable")
        manifest = response.json()
    except Exception:
        raise BrowserAcceptanceFailure("Deployed backend build identity unavailable") from None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "sourceSha"}
        or manifest.get("schema") != "athena.backend-build.v1"
        or manifest.get("sourceSha") != expected_sha
    ):
        raise BrowserAcceptanceFailure("Deployed backend build SHA mismatch")


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



def _require_live_surface_payload(response, *, backend_origin: str, path: str) -> None:
    """Bind Market and SEC browser evidence to a live, scoped API response.

    This is a deployment contract check, not independent source authentication.
    Never echo response bodies or staging URLs into acceptance logs.
    """
    try:
        if (
            response.status != 200
            or not _matches_backend_api(
                response.url, backend_origin=backend_origin, path=path
            )
            or "application/json" not in response.headers.get(
                "content-type", ""
            ).lower()
        ):
            raise ValueError("untrusted response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid envelope")
        data = payload.get("data")
        if path == "/api/v1/market/universe":
            if not isinstance(data, list) or not any(
                isinstance(asset, dict)
                and isinstance(asset.get("symbol"), str)
                and bool(asset["symbol"].strip())
                for asset in data
            ):
                raise ValueError("empty market universe")
        elif path == "/api/v1/market/universe/status":
            if (
                not isinstance(data, dict)
                or type(data.get("globallyUsableCount")) is not int
                or data["globallyUsableCount"] <= 0
                or type(data.get("activeCount")) is not int
                or data["activeCount"] <= 0
                or data.get("usingFallback") is not False
            ):
                raise ValueError("unusable or fallback market universe")
        elif path == "/api/v1/sec/institutional-holdings/latest":
            ciks = parse_qs(
                urlsplit(response.url).query, keep_blank_values=True
            ).get("cik", [])
            if len(ciks) != 1 or not re.fullmatch(r"[0-9]{1,10}", ciks[0]):
                raise ValueError("unbound CIK")
            if not isinstance(data, dict):
                raise ValueError("missing 13F data")
            source = urlsplit(data.get("sourceUrl", ""))
            expected_prefix = (
                f"/Archives/edgar/data/{int(ciks[0])}/"
            )
            if (
                source.scheme != "https"
                or source.hostname != "www.sec.gov"
                or source.username is not None
                or source.password is not None
                or source.port not in (None, 443)
                or not source.path.startswith(expected_prefix)
                or source.query or source.fragment
                or data.get("sourceProvider") != "SEC EDGAR"
                or data.get("advisoryStatus") != "no_advice"
                or data.get("productionEligible") is not False
                or data.get("automaticTrading") is not False
                or not isinstance(data.get("holdings"), list)
                or not data["holdings"]
                or not isinstance(payload.get("selectedFiling"), dict)
            ):
                raise ValueError("unverified 13F")
        else:
            raise ValueError("unexpected surface")
    except Exception:
        raise BrowserAcceptanceFailure("Deployed surface evidence invalid") from None


def verify_market_fault_recovery(page, *, backend_origin: str) -> None:
    """Market must remove old evidence on a controlled 503 and recover live."""
    path = "/api/v1/market/universe/status"

    def matches(url: str) -> bool:
        return _matches_backend_api(
            url, backend_origin=backend_origin, path=path
        )

    def reject(route) -> None:
        route.fulfill(
            status=503, content_type="application/json",
            body='{"detail":"controlled acceptance fault"}',
        )

    page.route(matches, reject)
    try:
        with page.expect_response(
            lambda response: response.status == 503 and matches(response.url),
            timeout=30000,
        ):
            page.get_by_role(
                "button", name="Actualizar mercado", exact=True
            ).click(timeout=15000)
        page.get_by_text(
            "No se pudo verificar el contexto global del mercado. "
            "Reintenta la consulta.", exact=True
        ).wait_for(state="visible", timeout=30000)
        if page.get_by_text(
            re.compile(r"UNIVERSO REAL PERSISTIDO")
        ).count():
            raise BrowserAcceptanceFailure(
                "Market failure retained stale universe"
            )
    finally:
        page.unroute(matches, reject)

    with page.expect_response(
        lambda response: response.status == 200 and matches(response.url),
        timeout=30000,
    ) as recovered:
        page.get_by_role(
            "button", name="Reintentar mercado", exact=True
        ).click(timeout=15000)
    _require_live_surface_payload(
        recovered.value, backend_origin=backend_origin, path=path
    )
    page.get_by_text(
        re.compile(r"UNIVERSO REAL PERSISTIDO")
    ).first.wait_for(state="visible", timeout=30000)


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



def verify_live_canonical_cycle(page, *, backend_origin: str) -> str:
    """Require live ATHENA/News/Investors evidence from one PIT research cycle.

    This verifies cross-artifact consistency, not independent provider truth.
    Neither payloads nor source fingerprints are printed on failure.
    """
    root = "/api/v1/recommendations/professional-research"
    def live(path: str) -> dict:
        response = _fetch_live_canonical_synthesis(
            page, backend_origin=backend_origin, path=root + path
        )
        try:
            envelope = response.json()
            if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
                raise ValueError("missing canonical data")
            return envelope["data"]
        except Exception:
            raise BrowserAcceptanceFailure("Canonical deployed research unavailable") from None

    def obj(value):
        if not isinstance(value, dict):
            raise ValueError("missing object")
        return value

    def digest(value):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("missing hash")
        return value

    try:
        athena = live("/athena-synthesis/latest")
        cycle = digest(athena.get("cycleHash"))
        news = live("/news-synthesis/latest")
        investors = live(f"/research-cycle/{cycle}/investors-synthesis")
        selection = obj(athena.get("selection"))
        synthesis = obj(athena.get("synthesis"))
        provenance = obj(athena.get("provenance"))
        fingerprint = digest(synthesis.get("inputFingerprint"))
        news_hash = digest(obj(news.get("persistence")).get("synthesisHash"))
        investors_hash = digest(obj(investors.get("persistence")).get("synthesisHash"))
        if not (
            athena.get("artifactBindingVerified") is True
            and selection.get("presentationOnly") is True
            and selection.get("recommendationInfluence") is False
            and selection.get("automaticTrading") is False
            and digest(provenance.get("inputFingerprint")) == fingerprint
            and news.get("cycleBindingVerified") is True
            and news.get("cycleHash") == cycle
            and news.get("presentationOnly") is True
            and news.get("recommendationInfluence") is False
            and news.get("automaticTrading") is False
            and investors.get("cycleBindingVerified") is True
            and investors.get("cycleHash") == cycle
            and investors.get("recommendationInfluence") is False
            and investors.get("automaticTrading") is False
            and digest(obj(provenance.get("news")).get("artifactHash")) == news_hash
            and digest(obj(provenance.get("investors")).get("artifactHash")) == investors_hash
        ):
            raise ValueError("inconsistent research binding")
        return cycle
    except (KeyError, TypeError, ValueError):
        raise BrowserAcceptanceFailure("Canonical deployed research binding invalid") from None


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

    market_universe = "/api/v1/market/universe"
    market_status = "/api/v1/market/universe/status"
    with page.expect_response(
        lambda response: _matches_backend_api(
            response.url, backend_origin=backend_origin, path=market_universe
        ), timeout=30000,
    ) as universe_response, page.expect_response(
        lambda response: _matches_backend_api(
            response.url, backend_origin=backend_origin, path=market_status
        ), timeout=30000,
    ) as status_response:
        _visit(page, "Mercado", "MERCADO")
    _require_live_surface_payload(
        universe_response.value, backend_origin=backend_origin,
        path=market_universe,
    )
    _require_live_surface_payload(
        status_response.value, backend_origin=backend_origin,
        path=market_status,
    )
    _heading(page, "MERCADO GLOBAL")
    page.get_by_text(
        re.compile(r"UNIVERSO REAL PERSISTIDO")
    ).first.wait_for(state="visible", timeout=30000)
    verify_market_fault_recovery(page, backend_origin=backend_origin)
    _back(page)
    _visit(page, "Noticias", "NOTICIAS")
    _heading(page, "ANÁLISIS ATHENA DE NOTICIAS")
    verify_news_refresh_scope(page, backend_origin=backend_origin)
    _back(page)
    sec_path = "/api/v1/sec/institutional-holdings/latest"
    with page.expect_response(
        lambda response: _matches_backend_api(
            response.url, backend_origin=backend_origin, path=sec_path
        ), timeout=30000,
    ) as sec_response:
        _visit(page, "Inversores", "INVERSORES")
    _require_live_surface_payload(
        sec_response.value, backend_origin=backend_origin, path=sec_path
    )
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
        "marketLiveHttpVerified": True,
        "marketControlledFaultRecoveryVerified": True,
        "sec13fLiveHttpVerified": True,
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
                stage = "deployed-backend-build-identity"
                verify_deployed_backend_build(
                    page, expected_sha=config.deployed_sha,
                    backend_origin=config.backend_origin,
                )
                stage = "live-canonical-provenance"
                verify_live_canonical_cycle(
                    page, backend_origin=config.backend_origin
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
        "deployedBackendBuildIdentityVerified": True,
        "deployedCanonicalCycleBindingVerified": True,
        "deployedFlutterBrowserE2EVerified": False,
        "twoOwnerBrowserIsolationVerified": False,
        "staleResponseOrderingVerified": True,
        "selectiveRefreshVerified": True,
        "productionAuthorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
