"""Regression coverage for compiled Flutter Web backend origin."""

from __future__ import annotations

import pytest

from scripts.flutter_web_backend_origin import validate_backend_origin


@pytest.mark.parametrize("origin,expected", [
    ("https://api.example.test", "https://api.example.test"),
    ("https://api.example.test/", "https://api.example.test"),
    ("https://api.example.test:8443", "https://api.example.test:8443"),
])
def test_valid_public_backend_origin(origin, expected):
    assert validate_backend_origin(origin) == expected


@pytest.mark.parametrize("origin", [
    "", "http://api.example.test", "https://localhost:8000",
    "https://127.0.0.1:8000", "https://[::1]:8443",
    "https://user:password@api.example.test",
    "https://api.example.test/path", "https://api.example.test/?token=abc",
    "https://api.example.test/#fragment", "https://api.example.test:invalid",
    " https://api.example.test", "https://api.example.test\\path",
    "https://api.example.test\n",
])
def test_unsafe_backend_origin_fails_closed(origin):
    with pytest.raises(ValueError, match="HTTPS backend origin"):
        validate_backend_origin(origin)
