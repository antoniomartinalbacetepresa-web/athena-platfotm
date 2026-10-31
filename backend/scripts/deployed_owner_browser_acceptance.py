"""Opt-in real HTTPS Flutter Web two-owner browser acceptance.

Two isolated Chromium contexts; no screenshots, traces, identities, tokens or
private digests are persisted. Only disposable staging sessions are revoked.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import httpx

from scripts.deployed_cross_surface_acceptance import (
    AcceptanceFailure, TestOwner, _env_owner, _owner_snapshot,
)
from scripts.deployed_flutter_browser_acceptance import (
    BrowserAcceptanceFailure, _matches_backend_api, validate_config,
    verify_deployed_backend_build, verify_deployed_web_build,
)

_PROTECTED_PATHS = (
    "/api/v1/auth/me",
    "/api/v1/user/profile/preferences",
    "/api/v1/user/profile/personalization",
    "/api/v1/user/portfolio",
)


class BrowserAuthorityObserver:
    """Keep browser-issued bearer tokens in memory; reject untrusted API origins."""

    def __init__(self, backend_origin: str):
        self.backend_origin = backend_origin
        self._tokens: set[str] = set()
        self._invalid = False

    def observe(self, request) -> None:
        try:
            url = urlsplit(request.url)
            if url.path not in _PROTECTED_PATHS:
                return
            authorization = request.headers.get("authorization", "")
            if not authorization:
                return
            if not _matches_backend_api(
                request.url, backend_origin=self.backend_origin, path=url.path
            ):
                self._invalid = True
                return
            if not authorization.startswith("Bearer ") or not authorization[7:]:
                self._invalid = True
                return
            self._tokens.add(authorization[7:])
        except (TypeError, ValueError):
            self._invalid = True

    def token(self) -> str:
        if self._invalid or len(self._tokens) != 1:
            raise BrowserAcceptanceFailure("Browser owner authority invalid or ambiguous")
        return next(iter(self._tokens))

    def cleanup_tokens(self) -> tuple[str, ...]:
        return tuple(self._tokens)


def _enable_semantics(page) -> None:
    placeholder = page.locator("flt-semantics-placeholder")
    if placeholder.count():
        placeholder.first.click(timeout=15000)


def _dashboard(page) -> None:
    page.goto("/", wait_until="domcontentloaded", timeout=45000)
    _enable_semantics(page)
    page.get_by_role("button", name="Perfil", exact=True).wait_for(timeout=30000)


def _login(page, owner: TestOwner) -> None:
    page.goto("/", wait_until="domcontentloaded", timeout=45000)
    _enable_semantics(page)
    page.get_by_role("button", name="ENTRAR CON CUENTA", exact=True).click(timeout=30000)
    page.get_by_label("Email", exact=True).fill(owner.username, timeout=15000)
    page.get_by_label("Contraseña", exact=True).fill(owner.password, timeout=15000)
    page.get_by_role("button", name="ENTRAR CON CUENTA", exact=True).click(timeout=15000)
    page.get_by_role("button", name="Perfil", exact=True).wait_for(timeout=30000)


def _profile(page, owner: TestOwner, other: TestOwner, *,
             backend_origin: str) -> None:
    page.get_by_role("button", name="Perfil", exact=True).click(timeout=15000)
    page.get_by_text("Identidad autenticada", exact=True).wait_for(timeout=30000)
    page.get_by_text(re.compile("^" + re.escape(owner.username) + "$", re.I)).wait_for(
        timeout=15000
    )
    if page.get_by_text(re.compile("^" + re.escape(other.username) + "$", re.I)).count():
        raise BrowserAcceptanceFailure("Other owner's identity visible in Profile")
    preferences = "/api/v1/user/profile/preferences"
    with page.expect_response(
        lambda r: _matches_backend_api(
            r.url, backend_origin=backend_origin, path=preferences
        ), timeout=30000,
    ) as refreshed:
        page.get_by_role("button", name="RECARGAR", exact=True).click(timeout=15000)
    if refreshed.value.status != 200:
        raise BrowserAcceptanceFailure("Owner preferences browser reload failed")
    page.get_by_text("Identidad autenticada", exact=True).wait_for(timeout=15000)


def _portfolio(page, *, backend_origin: str) -> None:
    _dashboard(page)
    page.get_by_role("button", name="Cartera", exact=True).click(timeout=15000)
    page.get_by_role("heading", name="MI CARTERA", exact=True).wait_for(timeout=30000)
    page.get_by_text("POSICIONES AUTENTICADAS", exact=True).wait_for(timeout=30000)
    portfolio = "/api/v1/user/portfolio"
    preferences = "/api/v1/user/profile/preferences"
    with page.expect_response(
        lambda r: _matches_backend_api(r.url, backend_origin=backend_origin, path=portfolio),
        timeout=30000,
    ) as portfolio_response, page.expect_response(
        lambda r: _matches_backend_api(r.url, backend_origin=backend_origin, path=preferences),
        timeout=30000,
    ) as preferences_response:
        page.get_by_role(
            "button", name="Actualizar cartera y preferencias", exact=True
        ).click(timeout=15000)
    if portfolio_response.value.status != 200 or preferences_response.value.status != 200:
        raise BrowserAcceptanceFailure("Owner-scoped browser refresh failed")
    page.get_by_text("POSICIONES AUTENTICADAS", exact=True).wait_for(timeout=15000)


def _revoked(client: httpx.Client, token: str) -> None:
    for path in _PROTECTED_PATHS:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 401:
            raise BrowserAcceptanceFailure("Revoked browser authority remained usable")


def _logout_ui(page) -> None:
    _dashboard(page)
    page.get_by_role("button", name="Perfil", exact=True).click(timeout=15000)
    page.get_by_role("button", name="CERRAR SESIÓN", exact=True).click(timeout=15000)
    page.get_by_role("button", name="ENTRAR CON CUENTA", exact=True).wait_for(
        timeout=30000
    )


def verify_two_owner_browser(browser, *, config, owner_a: TestOwner,
                             owner_b: TestOwner) -> dict[str, object]:
    """Live UI login, refresh, privacy, logout, revocation and B continuity."""
    if owner_a.username.casefold() == owner_b.username.casefold():
        raise BrowserAcceptanceFailure("Distinct staging owners required")
    contexts = []
    observers = []
    with httpx.Client(base_url=config.backend_origin, timeout=12.0,
                      follow_redirects=False, trust_env=False) as client:
        try:
            for _ in range(2):
                context = browser.new_context(
                    base_url=config.base_url,
                    viewport={"width": 1440, "height": 900},
                    service_workers="block",
                )
                contexts.append(context)
                observer = BrowserAuthorityObserver(config.backend_origin)
                observers.append(observer)
                page = context.new_page()
                page.on("request", observer.observe)
                verify_deployed_web_build(
                    page, expected_sha=config.deployed_sha,
                    expected_origin=config.base_url,
                    expected_backend_origin=config.backend_origin,
                )
                verify_deployed_backend_build(
                    page, expected_sha=config.deployed_sha,
                    backend_origin=config.backend_origin,
                )
            page_a, page_b = (context.pages[0] for context in contexts)
            _login(page_a, owner_a)
            _login(page_b, owner_b)
            _profile(page_a, owner_a, owner_b, backend_origin=config.backend_origin)
            _profile(page_b, owner_b, owner_a, backend_origin=config.backend_origin)
            _portfolio(page_a, backend_origin=config.backend_origin)
            _portfolio(page_b, backend_origin=config.backend_origin)
            token_a, token_b = (observer.token() for observer in observers)
            if token_a == token_b:
                raise BrowserAcceptanceFailure("Distinct browser authorities required")
            snapshot_a = _owner_snapshot(client, token_a, owner_a, "browser owner A")
            snapshot_b = _owner_snapshot(client, token_b, owner_b, "browser owner B")
            if (snapshot_a.owner_id == snapshot_b.owner_id or
                    not snapshot_a.position_ids.isdisjoint(snapshot_b.position_ids)):
                raise BrowserAcceptanceFailure("Browser owner isolation failed")
            _logout_ui(page_a)
            _revoked(client, token_a)
            page_a.get_by_role("button", name="Continuar como invitado").click(timeout=15000)
            page_a.get_by_role("button", name="Perfil", exact=True).click(timeout=15000)
            page_a.get_by_role("heading", name="Perfil protegido", exact=True).wait_for(
                timeout=30000
            )
            _portfolio(page_b, backend_origin=config.backend_origin)
            snapshot_b_after = _owner_snapshot(
                client, token_b, owner_b, "browser owner B after A logout"
            )
            if snapshot_b_after != snapshot_b:
                raise BrowserAcceptanceFailure("Other owner changed after browser logout")
            _logout_ui(page_b)
            _revoked(client, token_b)
            return {
                "status": "passed",
                "deployedTwoOwnerFlutterBrowserVerified": True,
                "ownerScopedProfileAndPortfolioRefreshVerified": True,
                "ownerRevocationAndOtherOwnerContinuityVerified": True,
                "anonymousProfileBoundaryVerified": True,
                "deployedExactShaWebAndBackendVerified": True,
                "productionAuthorization": False,
            }
        finally:
            for observer in observers:
                for token in observer.cleanup_tokens():
                    try:
                        client.post(
                            "/api/v1/auth/logout",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                    except httpx.RequestError:
                        pass
            for context in contexts:
                try:
                    context.close()
                except Exception:
                    pass


def main() -> int:
    try:
        config = validate_config(dict(os.environ))
        owner_a, owner_b = _env_owner("A"), _env_owner("B")
    except (BrowserAcceptanceFailure, AcceptanceFailure, ValueError):
        print(json.dumps({"status": "blocked", "reason": "Protected staging configuration unavailable"}))
        return 2
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                result = verify_two_owner_browser(
                    browser, config=config, owner_a=owner_a, owner_b=owner_b,
                )
            finally:
                browser.close()
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Deployed owner browser acceptance failed"}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
