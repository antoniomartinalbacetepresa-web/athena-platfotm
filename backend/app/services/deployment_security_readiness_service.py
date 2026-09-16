from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class DeploymentSecurityReadiness:
    checks: tuple[dict[str, Any], ...]

    @property
    def ready(self) -> bool:
        return all(check.get("passed") is True for check in self.checks)

    def to_api_dict(self) -> dict[str, Any]:
        blockers = [
            str(check["blocker"])
            for check in self.checks
            if check.get("passed") is not True
        ]
        return {
            "status": "deployment_security_diagnostic",
            "ready": self.ready,
            "passedCheckCount": sum(
                1 for check in self.checks if check.get("passed") is True
            ),
            "totalCheckCount": len(self.checks),
            "checks": list(self.checks),
            "blockers": blockers,
            "policy": {
                "secretsDisclosed": False,
                "productionDeploymentVerified": False,
                "offsiteBackupVerified": False,
                "smtpDeliveryVerified": False,
                "automaticSecretRotation": False,
                "productionHistoricalKeyRetirementVerified": False,
                "automaticTrading": False,
            },
        }


class DeploymentSecurityReadinessService:
    """Validate deploy-time security invariants without exposing secret material.

    This diagnostic intentionally distinguishes *configuration readiness* from
    proof that a production deployment, SMTP channel, secret-manager operation
    or off-site backup actually exists. It only reports boolean properties,
    blocker identifiers and non-secret ciphertext-version counts.
    """

    _AUTH_SECRET = "ATHENA_AUTH_SECRET"
    _PROFILE_KEY = "ATHENA_PROFILE_ENCRYPTION_KEY"
    _PROFILE_KEY_VERSION = "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION"
    _PREVIOUS_KEYS = "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"
    _RECOVERY_HOST = "ATHENA_RECOVERY_SMTP_HOST"
    _RECOVERY_PORT = "ATHENA_RECOVERY_SMTP_PORT"
    _RECOVERY_USERNAME = "ATHENA_RECOVERY_SMTP_USERNAME"
    _RECOVERY_PASSWORD = "ATHENA_RECOVERY_SMTP_PASSWORD"
    _RECOVERY_FROM = "ATHENA_RECOVERY_FROM_EMAIL"
    _RECOVERY_PUBLIC_URL = "ATHENA_RECOVERY_PUBLIC_URL"
    _RECOVERY_STARTTLS = "ATHENA_RECOVERY_SMTP_STARTTLS"
    _PROFILE_TABLE = "athena_user_profile_preferences"
    _PORTFOLIO_TABLE = "athena_user_portfolio_positions"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def evaluate(self) -> DeploymentSecurityReadiness:
        auth_secret = self._text(self._AUTH_SECRET)
        profile_key_text = self._text(self._PROFILE_KEY)
        profile_key = self._decode_32_byte_key(profile_key_text)
        profile_version = self._positive_int(self._text(self._PROFILE_KEY_VERSION) or "1")
        previous_keys_valid = self._previous_keyring_valid(
            self._text(self._PREVIOUS_KEYS),
            current_version=profile_version,
        )
        encrypted_storage = self._encrypted_storage_version_evidence(
            current_version=profile_version,
        )
        public_url = self._text(self._RECOVERY_PUBLIC_URL)
        smtp_host = self._text(self._RECOVERY_HOST)
        smtp_from = self._text(self._RECOVERY_FROM)
        smtp_port = self._valid_port(self._text(self._RECOVERY_PORT) or "587")
        smtp_username = self._text(self._RECOVERY_USERNAME)
        smtp_password = os.getenv(self._RECOVERY_PASSWORD) or ""
        smtp_credentials_coherent = bool(smtp_username) == bool(smtp_password)
        starttls_enabled = self._bool_env(self._RECOVERY_STARTTLS, default=True)

        auth_secret_bytes = auth_secret.encode("utf-8") if auth_secret else b""
        auth_profile_separated = bool(auth_secret_bytes) and profile_key is not None and (
            auth_secret_bytes != profile_key
            and auth_secret != profile_key_text
        )

        checks = (
            self._check(
                "auth_secret_strength",
                len(auth_secret_bytes) >= 32,
                "auth_secret_missing_or_too_short",
            ),
            self._check(
                "profile_key_strength",
                profile_key is not None,
                "profile_encryption_key_invalid",
            ),
            self._check(
                "profile_key_versioning",
                profile_version is not None and previous_keys_valid,
                "profile_keyring_invalid",
            ),
            self._check(
                "encrypted_storage_key_version_convergence",
                encrypted_storage["passed"],
                "encrypted_storage_still_depends_on_noncurrent_key",
                evidence=encrypted_storage["evidence"],
            ),
            self._check(
                "auth_profile_key_separation",
                auth_profile_separated,
                "auth_and_profile_keys_not_separated",
            ),
            self._check(
                "recovery_public_https",
                public_url.lower().startswith("https://"),
                "recovery_public_url_not_https",
            ),
            self._check(
                "recovery_smtp_endpoint",
                bool(smtp_host) and bool(smtp_from) and smtp_port,
                "recovery_smtp_endpoint_incomplete",
            ),
            self._check(
                "recovery_smtp_credentials",
                smtp_credentials_coherent,
                "recovery_smtp_credentials_incoherent",
            ),
            self._check(
                "recovery_transport_encryption",
                starttls_enabled,
                "recovery_smtp_tls_disabled",
            ),
        )
        return DeploymentSecurityReadiness(checks=checks)

    @staticmethod
    def _check(
        identifier: str,
        passed: bool,
        blocker: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": identifier,
            "passed": bool(passed),
            "blocker": blocker,
        }
        if evidence is not None:
            result["evidence"] = evidence
        return result

    def _encrypted_storage_version_evidence(
        self,
        *,
        current_version: int | None,
    ) -> dict[str, Any]:
        """Report whether persisted ciphertext metadata converges to the active key.

        This is deliberately narrower than a production key-retirement claim. It
        proves only that no persisted Profile/Portfolio ciphertext *declares* a
        dependency on another key version and that Portfolio encryption tuples
        are structurally complete. Actual secret-manager custody/deletion remains
        an external operational gate.
        """
        evidence: dict[str, Any] = {
            "currentKeyVersion": current_version,
            "profileCiphertextCount": 0,
            "portfolioCiphertextCount": 0,
            "nonCurrentCiphertextCount": 0,
            "malformedCiphertextCount": 0,
            "nonCurrentKeyVersions": [],
            "ciphertextIntegrityVerified": False,
            "productionKeyRetirementVerified": False,
        }
        if current_version is None:
            return {"passed": False, "evidence": evidence}

        database_path = getattr(self._database, "database_path", None)
        if database_path is not None and not database_path.exists():
            return {"passed": True, "evidence": evidence}

        non_current_versions: set[int] = set()
        try:
            with self._database.connect() as connection:
                if self._table_exists(connection, self._PROFILE_TABLE):
                    rows = connection.execute(
                        f"SELECT key_version FROM {self._PROFILE_TABLE}"
                    ).fetchall()
                    evidence["profileCiphertextCount"] = len(rows)
                    for row in rows:
                        version = self._row_positive_version(row["key_version"])
                        if version is None:
                            evidence["malformedCiphertextCount"] += 1
                        elif version != current_version:
                            evidence["nonCurrentCiphertextCount"] += 1
                            non_current_versions.add(version)

                if self._table_exists(connection, self._PORTFOLIO_TABLE):
                    rows = connection.execute(
                        f"""
                        SELECT average_purchase_price_key_version AS key_version,
                               average_purchase_price_nonce_b64 AS nonce_b64,
                               average_purchase_price_ciphertext_b64 AS ciphertext_b64
                        FROM {self._PORTFOLIO_TABLE}
                        """
                    ).fetchall()
                    for row in rows:
                        values = (
                            row["key_version"],
                            row["nonce_b64"],
                            row["ciphertext_b64"],
                        )
                        if all(value is None for value in values):
                            continue
                        evidence["portfolioCiphertextCount"] += 1
                        if any(value is None for value in values):
                            evidence["malformedCiphertextCount"] += 1
                            continue
                        version = self._row_positive_version(row["key_version"])
                        if version is None:
                            evidence["malformedCiphertextCount"] += 1
                        elif version != current_version:
                            evidence["nonCurrentCiphertextCount"] += 1
                            non_current_versions.add(version)
        except Exception:
            # Database/read failures are readiness blockers, never reasons to
            # infer that historical keys are safe to remove.
            evidence["malformedCiphertextCount"] += 1

        evidence["nonCurrentKeyVersions"] = sorted(non_current_versions)
        passed = (
            evidence["nonCurrentCiphertextCount"] == 0
            and evidence["malformedCiphertextCount"] == 0
        )
        return {"passed": passed, "evidence": evidence}

    @staticmethod
    def _table_exists(connection: Any, table_name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    @classmethod
    def _row_positive_version(cls, value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        return cls._positive_int(str(value).strip())

    @staticmethod
    def _text(name: str) -> str:
        return str(os.getenv(name) or "").strip()

    @staticmethod
    def _positive_int(value: str) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0 or str(parsed) != str(value).strip():
            return None
        return parsed

    @staticmethod
    def _valid_port(value: str) -> bool:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return False
        return 1 <= parsed <= 65535

    @staticmethod
    def _decode_32_byte_key(value: str) -> bytes | None:
        if not value:
            return None
        try:
            decoded = base64.b64decode(value, altchars=b"-_", validate=True)
        except Exception:
            return None
        return decoded if len(decoded) == 32 else None

    @classmethod
    def _previous_keyring_valid(
        cls,
        value: str,
        *,
        current_version: int | None,
    ) -> bool:
        if current_version is None:
            return False
        if not value:
            return True
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        for raw_version, raw_key in payload.items():
            version = cls._positive_int(str(raw_version).strip())
            if version is None or version == current_version:
                return False
            if not isinstance(raw_key, str) or cls._decode_32_byte_key(raw_key.strip()) is None:
                return False
        return True

    @staticmethod
    def _bool_env(name: str, *, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
        return False
