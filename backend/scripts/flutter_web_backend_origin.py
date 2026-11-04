"""Validate public HTTPS API origin embedded in Flutter Web release bundles."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


def validate_backend_origin(value: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(c.isspace() or ord(c) < 32 for c in value)
        or "\\" in value
    ):
        raise ValueError("Public HTTPS backend origin required")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or "@" in parsed.netloc or "%" in parsed.netloc
        ):
            raise ValueError("Public HTTPS backend origin required")
        _ = parsed.port
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError("Loopback backend origin is not deployable")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if address.is_loopback or address.is_unspecified:
                raise ValueError("Loopback backend origin is not deployable")
    except ValueError:
        raise ValueError("Public HTTPS backend origin required") from None
    return value.rstrip("/")


if __name__ == "__main__":
    try:
        print(validate_backend_origin(os.environ.get("ATHENA_WEB_BACKEND_ORIGIN", "")))
    except ValueError:
        raise SystemExit("Invalid public HTTPS backend origin") from None
