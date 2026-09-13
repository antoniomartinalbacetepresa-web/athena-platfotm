from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Apply defensive browser-facing headers to every HTTP response.

    HSTS is emitted only when the ASGI scope itself is HTTPS. We deliberately do
    not trust forwarded-protocol headers here because doing so safely requires a
    separately configured trusted-proxy boundary.
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

        await self.app(scope, receive, send_with_security_headers)
