from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.encrypted_user_profile_repository import EncryptedUserProfileRepository
from app.repositories.user_account_repository import UserAccountRepository
from app.repositories.user_portfolio_repository import UserPortfolioRepository
from app.services.deployment_security_readiness_service import (
    DeploymentSecurityReadinessService,
)


def _key(seed: int) -> str:
    return base64.urlsafe_b64encode(bytes([seed]) * 32).decode("ascii")


def _clear(monkeypatch) -> None:
    for name in (
        "ATHENA_AUTH_SECRET",
        "ATHENA_PROFILE_ENCRYPTION_KEY",
        "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION",
        "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
        "ATHENA_RECOVERY_SMTP_HOST",
        "ATHENA_RECOVERY_SMTP_PORT",
        "ATHENA_RECOVERY_SMTP_USERNAME",
        "ATHENA_RECOVERY_SMTP_PASSWORD",
        "ATHENA_RECOVERY_FROM_EMAIL",
        "ATHENA_RECOVERY_PUBLIC_URL",
        "ATHENA_RECOVERY_SMTP_STARTTLS",
    ):
        monkeypatch.delenv(name, raising=False)


def _secure_configuration(monkeypatch) -> tuple[str, str]:
    auth_secret = "auth-secret-material-that-is-longer-than-thirty-two-bytes"
    smtp_password = "smtp-password-must-never-be-returned"
    monkeypatch.setenv("ATHENA_AUTH_SECRET", auth_secret)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", _key(2))
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", "2")
    monkeypatch.setenv(
        "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
        json.dumps({"1": _key(1)}),
    )
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_PORT", "587")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_USERNAME", "athena")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_PASSWORD", smtp_password)
    monkeypatch.setenv("ATHENA_RECOVERY_FROM_EMAIL", "security@example.invalid")
    monkeypatch.setenv(
        "ATHENA_RECOVERY_PUBLIC_URL",
        "https://app.example.invalid/recover",
    )
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_STARTTLS", "true")
    return auth_secret, smtp_password


def _check(report: dict[str, object], identifier: str) -> dict[str, object]:
    checks = report["checks"]
    assert isinstance(checks, list)
    return next(item for item in checks if item["id"] == identifier)


def _owner(database: AthenaDatabase, email: str) -> int:
    account = UserAccountRepository(database).create(
        email=email,
        password_hash="test-hash-not-a-secret",
        display_name="Security Readiness",
    )
    return int(account["id"])


def test_missing_deployment_secrets_fail_closed(monkeypatch) -> None:
    _clear(monkeypatch)

    report = DeploymentSecurityReadinessService().evaluate().to_api_dict()

    assert report["ready"] is False
    assert report["passedCheckCount"] < report["totalCheckCount"]
    assert "auth_secret_missing_or_too_short" in report["blockers"]
    assert "profile_encryption_key_invalid" in report["blockers"]
    assert "auth_and_profile_keys_not_separated" in report["blockers"]
    assert "recovery_public_url_not_https" in report["blockers"]
    assert report["policy"]["productionDeploymentVerified"] is False
    assert report["policy"]["offsiteBackupVerified"] is False
    assert report["policy"]["smtpDeliveryVerified"] is False
    assert report["policy"]["productionHistoricalKeyRetirementVerified"] is False


def test_reused_auth_and_profile_key_is_rejected(monkeypatch) -> None:
    _clear(monkeypatch)
    shared_raw = bytes([9]) * 32
    shared_b64 = base64.urlsafe_b64encode(shared_raw).decode("ascii")
    # Auth secrets are textual, so test both direct textual equality and decoded
    # key separation by deliberately reusing the same encoded material.
    monkeypatch.setenv("ATHENA_AUTH_SECRET", shared_b64)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", shared_b64)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", "1")

    report = DeploymentSecurityReadinessService().evaluate().to_api_dict()

    assert _check(report, "auth_secret_strength")["passed"] is True
    assert _check(report, "profile_key_strength")["passed"] is True
    assert _check(report, "auth_profile_key_separation")["passed"] is False
    assert "auth_and_profile_keys_not_separated" in report["blockers"]


def test_invalid_historical_keyring_and_insecure_recovery_are_rejected(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv(
        "ATHENA_AUTH_SECRET",
        "another-independent-auth-secret-material-123456789",
    )
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", _key(2))
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", "2")
    monkeypatch.setenv(
        "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
        json.dumps({"2": _key(1)}),
    )
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_PORT", "70000")
    monkeypatch.setenv("ATHENA_RECOVERY_FROM_EMAIL", "security@example.invalid")
    monkeypatch.setenv("ATHENA_RECOVERY_PUBLIC_URL", "http://example.invalid/recover")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_STARTTLS", "false")

    report = DeploymentSecurityReadinessService().evaluate().to_api_dict()

    assert _check(report, "profile_key_versioning")["passed"] is False
    assert _check(report, "recovery_public_https")["passed"] is False
    assert _check(report, "recovery_smtp_endpoint")["passed"] is False
    assert _check(report, "recovery_transport_encryption")["passed"] is False


def test_secure_configuration_passes_without_claiming_operations(monkeypatch) -> None:
    _clear(monkeypatch)
    auth_secret, smtp_password = _secure_configuration(monkeypatch)

    report = DeploymentSecurityReadinessService().evaluate().to_api_dict()
    serialized = repr(report)

    assert report["ready"] is True
    assert report["passedCheckCount"] == report["totalCheckCount"] == 9
    assert report["blockers"] == []
    assert all(item["passed"] is True for item in report["checks"])
    assert report["policy"] == {
        "secretsDisclosed": False,
        "productionDeploymentVerified": False,
        "offsiteBackupVerified": False,
        "smtpDeliveryVerified": False,
        "automaticSecretRotation": False,
        "productionHistoricalKeyRetirementVerified": False,
        "automaticTrading": False,
    }
    storage = _check(report, "encrypted_storage_key_version_convergence")
    assert storage["evidence"]["productionKeyRetirementVerified"] is False
    assert storage["evidence"]["ciphertextIntegrityVerified"] is False
    assert auth_secret not in serialized
    assert smtp_password not in serialized
    assert _key(2) not in serialized
    assert _key(1) not in serialized


def test_persisted_legacy_ciphertext_blocks_key_retirement_until_both_stores_migrate(
    tmp_path, monkeypatch
) -> None:
    _clear(monkeypatch)
    database = AthenaDatabase(tmp_path / "athena.db")

    # Persist real encrypted Profile and Portfolio rows under v1.
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", _key(1))
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", "1")
    owner_id = _owner(database, "legacy-storage@example.com")
    EncryptedUserProfileRepository(database).upsert(
        owner_user_id=owner_id,
        preferences={"riskTolerance": "balanced"},
    )
    UserPortfolioRepository(database).upsert(
        owner_user_id=owner_id,
        symbol="AAPL",
        exchange="NASDAQ",
        quantity=2,
        average_purchase_price=180.0,
    )
    # A position without a declared cost basis is not ciphertext and must not
    # create a false retirement blocker.
    UserPortfolioRepository(database).upsert(
        owner_user_id=owner_id,
        symbol="BRK.B",
        exchange="NYSE",
        quantity=1,
        average_purchase_price=None,
    )

    _secure_configuration(monkeypatch)
    before = DeploymentSecurityReadinessService(database).evaluate().to_api_dict()
    storage_before = _check(before, "encrypted_storage_key_version_convergence")

    assert storage_before["passed"] is False
    assert storage_before["evidence"] == {
        "currentKeyVersion": 2,
        "profileCiphertextCount": 1,
        "portfolioCiphertextCount": 1,
        "nonCurrentCiphertextCount": 2,
        "malformedCiphertextCount": 0,
        "nonCurrentKeyVersions": [1],
        "ciphertextIntegrityVerified": False,
        "productionKeyRetirementVerified": False,
    }
    assert "encrypted_storage_still_depends_on_noncurrent_key" in before["blockers"]

    profile = EncryptedUserProfileRepository(database)
    portfolio = UserPortfolioRepository(database)
    assert profile.reencrypt_all_to_current_key() == 1
    assert portfolio.reencrypt_all_average_purchase_prices_to_current_key() == 1

    after = DeploymentSecurityReadinessService(database).evaluate().to_api_dict()
    storage_after = _check(after, "encrypted_storage_key_version_convergence")
    assert storage_after["passed"] is True
    assert storage_after["evidence"]["nonCurrentCiphertextCount"] == 0
    assert storage_after["evidence"]["nonCurrentKeyVersions"] == []

    # Only now can the historical key be removed without breaking either store.
    monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS", raising=False)
    assert EncryptedUserProfileRepository(database).get_for_owner(owner_id)["preferences"] == {
        "riskTolerance": "balanced"
    }
    positions = UserPortfolioRepository(database).list_for_owner(owner_id)
    by_symbol = {item["symbol"]: item["averagePurchasePrice"] for item in positions}
    assert by_symbol["AAPL"] == 180.0
    assert by_symbol["BRK.B"] is None

    retired = DeploymentSecurityReadinessService(database).evaluate().to_api_dict()
    assert _check(retired, "encrypted_storage_key_version_convergence")["passed"] is True
    # This remains an engineering diagnostic, not evidence that a production
    # secret manager actually deleted v1.
    assert retired["policy"]["productionHistoricalKeyRetirementVerified"] is False


def test_partial_portfolio_ciphertext_tuple_fails_closed(tmp_path, monkeypatch) -> None:
    _clear(monkeypatch)
    _secure_configuration(monkeypatch)
    database = AthenaDatabase(tmp_path / "athena.db")
    owner_id = _owner(database, "malformed-storage@example.com")
    UserPortfolioRepository(database).upsert(
        owner_user_id=owner_id,
        symbol="MSFT",
        exchange="NASDAQ",
        quantity=1,
        average_purchase_price=400.0,
    )

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_user_portfolio_positions
            SET average_purchase_price_nonce_b64 = NULL
            WHERE owner_user_id = ?
            """,
            (owner_id,),
        )

    report = DeploymentSecurityReadinessService(database).evaluate().to_api_dict()
    storage = _check(report, "encrypted_storage_key_version_convergence")
    assert storage["passed"] is False
    assert storage["evidence"]["portfolioCiphertextCount"] == 1
    assert storage["evidence"]["malformedCiphertextCount"] == 1
    assert "encrypted_storage_still_depends_on_noncurrent_key" in report["blockers"]


def test_security_readiness_endpoint_never_discloses_secret_material(monkeypatch) -> None:
    _clear(monkeypatch)
    auth_secret, smtp_password = _secure_configuration(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/v1/readiness/security")

    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert body["status"] == "deployment_security_diagnostic"
    assert body["ready"] is True
    assert body["policy"]["secretsDisclosed"] is False
    assert body["policy"]["productionHistoricalKeyRetirementVerified"] is False
    assert auth_secret not in serialized
    assert smtp_password not in serialized
    assert _key(2) not in serialized
    assert _key(1) not in serialized
