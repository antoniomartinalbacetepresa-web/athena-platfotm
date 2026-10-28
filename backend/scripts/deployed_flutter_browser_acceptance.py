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
    return BrowserConfig(base_url=base.rstrip("/") + "/", deployed_sha=deployed)


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


def verify_guest_research(page) -> dict[str, bool]:
    """Check real deployed navigation and explicitly scoped fault recovery."""
    seen: set[str] = set()

    def record(response) -> None:
        path = urlsplit(response.url).path
        if response.status == 200 and path.endswith("/athena-synthesis/latest"):
            seen.add("athena")
        if response.status == 200 and path.endswith("/news-synthesis/latest"):
            seen.add("news")

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
    pattern = "**/api/v1/recommendations/professional-research/athena-synthesis/latest*"

    def reject(route) -> None:
        route.fulfill(
            status=503, content_type="application/json",
            body='{"detail":"controlled acceptance fault"}',
        )

    page.route(pattern, reject)
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
        page.unroute(pattern, reject)
    page.get_by_role("button", name="Reintentar", exact=True).click()
    page.get_by_text("Fuentes verificadas", exact=True).wait_for(
        state="visible", timeout=30000
    )
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
                stage = "guest-research"
                result = verify_guest_research(context.new_page())
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
        "deployedFlutterBrowserE2EVerified": False,
        "twoOwnerBrowserIsolationVerified": False,
        "staleResponseOrderingVerified": False,
        "selectiveRefreshVerified": False,
        "productionAuthorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
