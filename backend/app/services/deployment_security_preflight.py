from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SecurityCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class SecurityPreflightReport:
    checks: tuple[SecurityCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": check.name, "ok": check.ok, "message": check.message}
                for check in self.checks
            ],
        }


class DeploymentSecurityPreflight:
    """Validate deployment secret configuration without exposing secret values.

    This is an application-side fail-closed control. It deliberately does not
    claim to replace an external secret manager, access policy, key custody or
    production rotation procedure.
    """

    AUTH_SECRET_ENV = "ATHENA_AUTH_SECRET"
    PROFILE_KEY_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY"
    PROFILE_KEY_VERSION_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION"
    PROFILE_PREVIOUS_KEYS_ENV = "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"
    MIN_AUTH_SECRET_BYTES = 32
    PROFILE_KEY_BYTES = 32

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = dict(os.environ if environment is None else environment)

    def run(self) -> SecurityPreflightReport:
        checks = (
            self._check_auth_secret(),
            self._check_profile_current_key(),
            self._check_profile_key_version(),
            self._check_profile_previous_keyring(),
            self._check_secret_separation(),
        )
        return SecurityPreflightReport(checks=checks)

    def require_valid(self) -> SecurityPreflightReport:
        report = self.run()
        if not report.ok:
            failed = ", ".join(check.name for check in report.checks if not check.ok)
            raise RuntimeError(f"Deployment security preflight failed: {failed}")
        return report

    def _check_auth_secret(self) -> SecurityCheck:
        value = self._environment.get(self.AUTH_SECRET_ENV, "").strip()
        if not value:
            return self._fail("auth-secret", "ATHENA_AUTH_SECRET is required.")
        if len(value.encode("utf-8")) < self.MIN_AUTH_SECRET_BYTES:
            return self._fail("auth-secret", "ATHENA_AUTH_SECRET must contain at least 32 bytes.")
        return self._pass("auth-secret", "Authentication signing secret is present and meets the minimum length.")

    def _check_profile_current_key(self) -> SecurityCheck:
        configured = self._environment.get(self.PROFILE_KEY_ENV, "").strip()
        if not configured:
            return self._fail("profile-current-key", "ATHENA_PROFILE_ENCRYPTION_KEY is required.")
        decoded = self._decode_key(configured)
        if decoded is None:
            return self._fail("profile-current-key", "Profile encryption key must be valid URL-safe/base64 data.")
        if len(decoded) != self.PROFILE_KEY_BYTES:
            return self._fail("profile-current-key", "Profile encryption key must decode to exactly 32 bytes.")
        return self._pass("profile-current-key", "Current profile encryption key has a valid 256-bit encoding.")

    def _check_profile_key_version(self) -> SecurityCheck:
        configured = self._environment.get(self.PROFILE_KEY_VERSION_ENV, "1").strip()
        try:
            version = int(configured)
        except ValueError:
            return self._fail("profile-key-version", "Profile encryption key version must be a positive integer.")
        if version <= 0 or str(version) != configured:
            return self._fail("profile-key-version", "Profile encryption key version must be a canonical positive integer.")
        return self._pass("profile-key-version", "Profile encryption key version is valid.")

    def _check_profile_previous_keyring(self) -> SecurityCheck:
        configured = self._environment.get(self.PROFILE_PREVIOUS_KEYS_ENV, "").strip()
        if not configured:
            return self._pass("profile-previous-keyring", "No historical profile keys are configured.")
        try:
            payload = json.loads(configured)
        except json.JSONDecodeError:
            return self._fail("profile-previous-keyring", "Historical profile keyring must contain valid JSON.")
        if not isinstance(payload, dict):
            return self._fail("profile-previous-keyring", "Historical profile keyring must be a JSON object.")

        current_raw = self._environment.get(self.PROFILE_KEY_VERSION_ENV, "1").strip()
        current_version = int(current_raw) if current_raw.isdigit() and int(current_raw) > 0 else None
        seen_keys: set[bytes] = set()
        current_key = self._decode_key(self._environment.get(self.PROFILE_KEY_ENV, "").strip())
        if current_key is not None:
            seen_keys.add(current_key)

        for raw_version, raw_key in payload.items():
            version_text = str(raw_version).strip()
            if not version_text.isdigit() or int(version_text) <= 0 or str(int(version_text)) != version_text:
                return self._fail("profile-previous-keyring", "Every historical key version must be a canonical positive integer.")
            if current_version is not None and int(version_text) == current_version:
                return self._fail("profile-previous-keyring", "Current profile key version cannot also appear in the historical keyring.")
            if not isinstance(raw_key, str) or not raw_key.strip():
                return self._fail("profile-previous-keyring", "Historical profile keys must be non-empty strings.")
            decoded = self._decode_key(raw_key.strip())
            if decoded is None or len(decoded) != self.PROFILE_KEY_BYTES:
                return self._fail("profile-previous-keyring", "Every historical profile key must decode to exactly 32 bytes.")
            if decoded in seen_keys:
                return self._fail("profile-previous-keyring", "Profile encryption keys must not be reused across versions.")
            seen_keys.add(decoded)

        return self._pass("profile-previous-keyring", "Historical profile keyring is structurally valid and contains no reused keys.")

    def _check_secret_separation(self) -> SecurityCheck:
        auth_secret = self._environment.get(self.AUTH_SECRET_ENV, "").strip().encode("utf-8")
        profile_key = self._decode_key(self._environment.get(self.PROFILE_KEY_ENV, "").strip())
        if auth_secret and profile_key is not None and auth_secret == profile_key:
            return self._fail("secret-separation", "Authentication and profile-encryption secrets must be independent.")
        return self._pass("secret-separation", "Authentication and profile-encryption secret material is not reused verbatim.")

    @staticmethod
    def _decode_key(value: str) -> bytes | None:
        if not value:
            return None
        try:
            return base64.b64decode(value, altchars=b"-_", validate=True)
        except Exception:
            return None

    @staticmethod
    def _pass(name: str, message: str) -> SecurityCheck:
        return SecurityCheck(name=name, ok=True, message=message)

    @staticmethod
    def _fail(name: str, message: str) -> SecurityCheck:
        return SecurityCheck(name=name, ok=False, message=message)
