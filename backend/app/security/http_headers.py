from __future__ import annotations

import os

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_PRIVATE_PRODUCTION_SURFACES = frozenset({"/docs", "/redoc", "/openapi.json"})
_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


def _is_production_runtime() -> bool:
    """Return whether the process explicitly declares a production runtime.

    Development remains the default so local API documentation keeps working.
    Production hardening is opt-in through ATHENA_ENV=production (or prod), which
    avoids guessing deployment state from host names or proxy-controlled headers.
    """

    return os.getenv("ATHENA_ENV", "").strip().lower() in _PRODUCTION_ENVIRONMENTS


class SecurityHeadersMiddleware:
    """Apply defensive browser-facing controls to every HTTP response.

    HSTS is emitted only when the ASGI scope itself is HTTPS. We deliberately do
    not trust forwarded-protocol headers here because doing so safely requires a
    separately configured trusted-proxy boundary.

    Interactive API documentation and the OpenAPI schema remain available for
    development, but an explicitly declared production runtime returns the same
    generic 404 for those surfaces. This reduces unnecessary production attack
    surface without pretending that hiding documentation protects the APIs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = scope.get("scheme") == "https"

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
                if is_https:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                elif "strict-transport-security" in headers:
                    del headers["strict-transport-security"]

            await send(message)

        if _is_production_runtime() and scope.get("path") in _PRIVATE_PRODUCTION_SURFACES:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            await response(scope, receive, send_with_security_headers)
            return

        await self.app(scope, receive, send_with_security_headers)
