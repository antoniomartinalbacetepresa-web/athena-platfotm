"""Shared fail-closed validation of the public password-recovery destination.

A recovery link contains a bearer token. Do not allow URL components that can
redirect, conceal, or misplace the token before delivery.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def valid_public_recovery_url(value: str) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    # Backslashes have inconsistent URL parsing semantics between clients.
    # Reject raw whitespace and control characters rather than normalizing.
    if "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    # Empty query/fragment delimiters also break the single-token URL contract.
    if "?" in value or "#" in value or parsed.netloc.endswith(":"):
        return False
    if "%" in parsed.netloc:
        return False
    return port is None or 1 <= port <= 65535
