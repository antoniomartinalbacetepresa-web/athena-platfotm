from __future__ import annotations

import base64
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.encrypted_user_profile_repository import EncryptedUserProfileRepository
from app.repositories.user_account_repository import UserAccountRepository


def _key(seed: int) -> str:
    return base64.urlsafe_b64encode(bytes([seed]) * 32).decode("ascii")


def _database(tmp_path) -> AthenaDatabase:
    return AthenaDatabase(tmp_path / "athena-test.sqlite3")


def _owner(database: AthenaDatabase, email: str = "owner@example.com") -> int:
    user = UserAccountRepository(database).create(
        email=email,
        password_hash="argon2-test-hash",
        display_name="Owner",
    )
    return int(user["id"])


def _configure(monkeypatch, *, current_version: int, current_key: str, previous=None) -> None:
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", current_key)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", str(current_version))
    if previous is None:
        monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS", raising=False)
    else:
        monkeypatch.setenv(
            "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
            json.dumps(previous, separators=(",", ":")),
        )


def test_new_writes_use_configured_current_key_version(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)
    owner_id = _owner(database)
    _configure(monkeypatch, current_version=2, current_key=_key(2), previous={"1": _key(1)})

    repository = EncryptedUserProfileRepository(database)
    repository.upsert(
        owner_user_id=owner_id,
        preferences={"riskProfile": "balanced", "baseCurrency": "EUR"},
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT key_version, nonce_b64, ciphertext_b64 FROM athena_user_profile_preferences WHERE owner_user_id = ?",
            (owner_id,),
        ).fetchone()
    assert row is not None
    assert int(row["key_version"]) == 2
    assert "balanced" not in str(row["ciphertext_b64"])
    assert "EUR" not in str(row["ciphertext_b64"])


def test_previous_version_remains_readable_and_can_be_migrated(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)
    owner_id = _owner(database)
    v1_key = _key(1)
    v2_key = _key(2)

    _configure(monkeypatch, current_version=1, current_key=v1_key)
    v1_repository = EncryptedUserProfileRepository(database)
    v1_repository.upsert(
        owner_user_id=owner_id,
        preferences={"riskProfile": "growth", "horizonYears": 10},
    )

    _configure(monkeypatch, current_version=2, current_key=v2_key, previous={"1": v1_key})
    rotating_repository = EncryptedUserProfileRepository(database)
    before = rotating_repository.get_for_owner(owner_id)
    assert before is not None
    assert before["preferences"] == {"horizonYears": 10, "riskProfile": "growth"}

    assert rotating_repository.reencrypt_all_to_current_key() == 1
    assert rotating_repository.reencrypt_all_to_current_key() == 0

    with database.connect() as connection:
        row = connection.execute(
            "SELECT key_version FROM athena_user_profile_preferences WHERE owner_user_id = ?",
            (owner_id,),
        ).fetchone()
    assert row is not None
    assert int(row["key_version"]) == 2

    _configure(monkeypatch, current_version=2, current_key=v2_key)
    current_only_repository = EncryptedUserProfileRepository(database)
    after = current_only_repository.get_for_owner(owner_id)
    assert after is not None
    assert after["preferences"] == {"horizonYears": 10, "riskProfile": "growth"}


def test_unknown_historical_key_version_fails_closed(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)
    owner_id = _owner(database)
    _configure(monkeypatch, current_version=1, current_key=_key(1))
    repository = EncryptedUserProfileRepository(database)
    repository.upsert(owner_user_id=owner_id, preferences={"riskProfile": "balanced"})

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_user_profile_preferences SET key_version = 7 WHERE owner_user_id = ?",
            (owner_id,),
        )

    _configure(monkeypatch, current_version=2, current_key=_key(2), previous={"1": _key(1)})
    repository = EncryptedUserProfileRepository(database)
    with pytest.raises(RuntimeError, match="versión 7 no está disponible"):
        repository.get_for_owner(owner_id)
    with pytest.raises(RuntimeError, match="versión 7 no está disponible"):
        repository.reencrypt_all_to_current_key()


def test_migration_rolls_back_if_any_profile_cannot_be_decrypted(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)
    owner_a = _owner(database, "a@example.com")
    owner_b = _owner(database, "b@example.com")
    v1_key = _key(1)

    _configure(monkeypatch, current_version=1, current_key=v1_key)
    repository = EncryptedUserProfileRepository(database)
    repository.upsert(owner_user_id=owner_a, preferences={"riskProfile": "balanced"})
    repository.upsert(owner_user_id=owner_b, preferences={"riskProfile": "growth"})

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_user_profile_preferences SET ciphertext_b64 = ? WHERE owner_user_id = ?",
            (base64.urlsafe_b64encode(b"tampered").decode("ascii"), owner_b),
        )

    _configure(monkeypatch, current_version=2, current_key=_key(2), previous={"1": v1_key})
    rotating_repository = EncryptedUserProfileRepository(database)
    with pytest.raises(RuntimeError, match="verificación de integridad"):
        rotating_repository.reencrypt_all_to_current_key()

    with database.connect() as connection:
        versions = connection.execute(
            "SELECT owner_user_id, key_version FROM athena_user_profile_preferences ORDER BY owner_user_id"
        ).fetchall()
    assert [(int(row["owner_user_id"]), int(row["key_version"])) for row in versions] == [
        (owner_a, 1),
        (owner_b, 1),
    ]


def test_previous_key_configuration_is_strict_and_unambiguous(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)

    _configure(monkeypatch, current_version=2, current_key=_key(2), previous={"2": _key(1)})
    with pytest.raises(RuntimeError, match="no puede repetirse"):
        EncryptedUserProfileRepository(database)

    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS", "not-json")
    with pytest.raises(RuntimeError, match="JSON válido"):
        EncryptedUserProfileRepository(database)

    monkeypatch.setenv(
        "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
        json.dumps({"1": base64.urlsafe_b64encode(b"short").decode("ascii")}),
    )
    with pytest.raises(RuntimeError, match="exactamente 32 bytes"):
        EncryptedUserProfileRepository(database)


def test_current_key_version_must_be_positive_integer(monkeypatch, tmp_path) -> None:
    database = _database(tmp_path)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", _key(2))
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", "0")
    monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS", raising=False)

    with pytest.raises(RuntimeError, match="entero positivo"):
        EncryptedUserProfileRepository(database)
