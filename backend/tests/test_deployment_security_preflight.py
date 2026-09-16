from __future__ import annotations

import base64
import json

import pytest

from app.services.deployment_security_preflight import DeploymentSecurityPreflight


def _key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii")


def _valid_environment() -> dict[str, str]:
    return {
        "ATHENA_AUTH_SECRET": "auth-secret-with-at-least-thirty-two-bytes-12345",
        "ATHENA_PROFILE_ENCRYPTION_KEY": _key(7),
        "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION": "2",
        "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS": json.dumps({"1": _key(3)}),
    }


def test_preflight_accepts_independent_valid_secrets_and_keyring() -> None:
    report = DeploymentSecurityPreflight(_valid_environment()).run()

    assert report.ok is True
    payload = report.as_dict()
    assert payload["ok"] is True
    assert all(check["ok"] for check in payload["checks"])
    rendered = json.dumps(payload)
    assert _valid_environment()["ATHENA_AUTH_SECRET"] not in rendered
    assert _valid_environment()["ATHENA_PROFILE_ENCRYPTION_KEY"] not in rendered


def test_preflight_fails_closed_when_required_secrets_are_missing() -> None:
    service = DeploymentSecurityPreflight({})
    report = service.run()

    assert report.ok is False
    assert {check.name for check in report.checks if not check.ok} >= {
        "auth-secret",
        "profile-current-key",
    }
    with pytest.raises(RuntimeError, match="Deployment security preflight failed"):
        service.require_valid()


def test_preflight_rejects_short_auth_secret_and_invalid_profile_key() -> None:
    environment = _valid_environment()
    environment["ATHENA_AUTH_SECRET"] = "too-short"
    environment["ATHENA_PROFILE_ENCRYPTION_KEY"] = "not-base64***"

    report = DeploymentSecurityPreflight(environment).run()

    failures = {check.name for check in report.checks if not check.ok}
    assert "auth-secret" in failures
    assert "profile-current-key" in failures


def test_preflight_rejects_noncanonical_or_nonpositive_key_versions() -> None:
    for version in ("0", "-1", "01", "v2"):
        environment = _valid_environment()
        environment["ATHENA_PROFILE_ENCRYPTION_KEY_VERSION"] = version
        report = DeploymentSecurityPreflight(environment).run()
        assert any(check.name == "profile-key-version" and not check.ok for check in report.checks)


def test_preflight_rejects_current_version_inside_historical_keyring() -> None:
    environment = _valid_environment()
    environment["ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"] = json.dumps({"2": _key(3)})

    report = DeploymentSecurityPreflight(environment).run()

    assert any(check.name == "profile-previous-keyring" and not check.ok for check in report.checks)


def test_preflight_rejects_reused_encryption_key_across_versions() -> None:
    environment = _valid_environment()
    environment["ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"] = json.dumps(
        {"1": _key(3), "3": _key(3)}
    )

    report = DeploymentSecurityPreflight(environment).run()

    assert any(check.name == "profile-previous-keyring" and not check.ok for check in report.checks)


def test_preflight_rejects_auth_and_profile_secret_reuse() -> None:
    raw = b"a" * 32
    environment = _valid_environment()
    environment["ATHENA_AUTH_SECRET"] = raw.decode("ascii")
    environment["ATHENA_PROFILE_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(raw).decode("ascii")

    report = DeploymentSecurityPreflight(environment).run()

    assert any(check.name == "secret-separation" and not check.ok for check in report.checks)


def test_preflight_never_returns_secret_values_in_failure_messages() -> None:
    environment = _valid_environment()
    environment["ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"] = "super-sensitive-not-json"

    payload = DeploymentSecurityPreflight(environment).run().as_dict()
    rendered = json.dumps(payload)

    assert "super-sensitive-not-json" not in rendered
    assert environment["ATHENA_AUTH_SECRET"] not in rendered
    assert environment["ATHENA_PROFILE_ENCRYPTION_KEY"] not in rendered
