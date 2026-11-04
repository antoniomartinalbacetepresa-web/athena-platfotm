from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.database.athena_database import AthenaDatabase


class EncryptedUserProfileRepository:
    _TABLE = "athena_user_profile_preferences"
    _KEY_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY"
    _KEY_VERSION_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION"
    _PREVIOUS_KEYS_ENV = "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"
    _DEFAULT_KEY_VERSION = 1
    _NONCE_BYTES = 12

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._key_version, self._keys = self._load_keyring()
        self._aesgcm = AESGCM(self._keys[self._key_version])
        self._database.initialize()
        self._ensure_table()

    def get_for_owner(self, owner_user_id: int) -> dict[str, Any] | None:
        owner_id = self._owner_id(owner_user_id)
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT key_version, nonce_b64, ciphertext_b64, created_at, updated_at FROM {self._TABLE} WHERE owner_user_id = ? LIMIT 1",
                (owner_id,),
            ).fetchone()
        if row is None:
            return None
        preferences = self._decrypt_preferences(owner_id=owner_id, row=row)
        return {
            "preferences": preferences,
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    def upsert(self, *, owner_user_id: int, preferences: dict[str, Any]) -> dict[str, Any]:
        owner_id = self._owner_id(owner_user_id)
        plaintext = self._serialize_preferences(preferences)
        nonce, ciphertext = self._encrypt(
            owner_id=owner_id,
            key_version=self._key_version,
            plaintext=plaintext,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    owner_user_id, key_version, nonce_b64, ciphertext_b64, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id) DO UPDATE SET
                    key_version = excluded.key_version,
                    nonce_b64 = excluded.nonce_b64,
                    ciphertext_b64 = excluded.ciphertext_b64,
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    self._key_version,
                    self._encode_b64(nonce),
                    self._encode_b64(ciphertext),
                    now,
                    now,
                ),
            )
        stored = self.get_for_owner(owner_id)
        if stored is None:
            raise RuntimeError("El perfil no pudo recuperarse tras persistirlo.")
        return stored

    def reencrypt_all_to_current_key(self) -> int:
        """Re-encrypt every legacy profile with the configured current key.

        The migration is explicit and transactional. A missing historical key or
        any integrity failure aborts the transaction instead of leaving a mixed,
        partially migrated data set.
        """
        migrated = 0
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT owner_user_id, key_version, nonce_b64, ciphertext_b64 FROM {self._TABLE} ORDER BY owner_user_id"
            ).fetchall()
            for row in rows:
                owner_id = self._owner_id(int(row["owner_user_id"]))
                key_version = int(row["key_version"])
                if key_version == self._key_version:
                    continue
                preferences = self._decrypt_preferences(owner_id=owner_id, row=row)
                plaintext = self._serialize_preferences(preferences)
                nonce, ciphertext = self._encrypt(
                    owner_id=owner_id,
                    key_version=self._key_version,
                    plaintext=plaintext,
                )
                connection.execute(
                    f"""
                    UPDATE {self._TABLE}
                    SET key_version = ?, nonce_b64 = ?, ciphertext_b64 = ?, updated_at = ?
                    WHERE owner_user_id = ? AND key_version = ?
                    """,
                    (
                        self._key_version,
                        self._encode_b64(nonce),
                        self._encode_b64(ciphertext),
                        now,
                        owner_id,
                        key_version,
                    ),
                )
                migrated += 1
        return migrated

    def delete_for_owner(self, owner_user_id: int) -> bool:
        owner_id = self._owner_id(owner_user_id)
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {self._TABLE} WHERE owner_user_id = ?",
                (owner_id,),
            )
        return cursor.rowcount == 1

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    owner_user_id INTEGER PRIMARY KEY,
                    key_version INTEGER NOT NULL,
                    nonce_b64 TEXT NOT NULL,
                    ciphertext_b64 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id) REFERENCES athena_user_accounts(id) ON DELETE CASCADE
                );
                """
            )

    def _decrypt_preferences(self, *, owner_id: int, row: Any) -> dict[str, Any]:
        key_version = int(row["key_version"])
        key = self._keys.get(key_version)
        if key is None:
            raise RuntimeError(
                f"La clave de cifrado del perfil para la versión {key_version} no está disponible."
            )
        try:
            nonce = self._decode_b64(str(row["nonce_b64"]))
            ciphertext = self._decode_b64(str(row["ciphertext_b64"]))
            plaintext = AESGCM(key).decrypt(
                nonce,
                ciphertext,
                self._associated_data(owner_id, key_version),
            )
            preferences = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("El perfil cifrado no supera la verificación de integridad.") from exc
        if not isinstance(preferences, dict):
            raise RuntimeError("El perfil cifrado no contiene un objeto válido.")
        return preferences

    def _encrypt(
        self,
        *,
        owner_id: int,
        key_version: int,
        plaintext: bytes,
    ) -> tuple[bytes, bytes]:
        key = self._keys.get(key_version)
        if key is None:
            raise RuntimeError(
                f"La clave de cifrado del perfil para la versión {key_version} no está disponible."
            )
        nonce = os.urandom(self._NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext,
            self._associated_data(owner_id, key_version),
        )
        return nonce, ciphertext

    @classmethod
    def _serialize_preferences(cls, preferences: dict[str, Any]) -> bytes:
        if not isinstance(preferences, dict) or not preferences:
            raise ValueError("preferences debe ser un objeto no vacío.")
        return json.dumps(
            preferences,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def _load_keyring(cls) -> tuple[int, dict[int, bytes]]:
        current_version = cls._load_current_version()
        current_key = cls._load_required_key(cls._KEY_ENV)
        keys: dict[int, bytes] = {current_version: current_key}

        configured_previous = os.getenv(cls._PREVIOUS_KEYS_ENV)
        if configured_previous is None or not configured_previous.strip():
            return current_version, keys
        try:
            payload = json.loads(configured_previous)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Las claves históricas del perfil no contienen JSON válido.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Las claves históricas del perfil deben ser un objeto JSON.")

        for raw_version, raw_key in payload.items():
            try:
                version = int(raw_version)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("La versión de una clave histórica del perfil no es válida.") from exc
            if version <= 0 or str(version) != str(raw_version).strip():
                raise RuntimeError("La versión de una clave histórica del perfil debe ser un entero positivo.")
            if version == current_version:
                raise RuntimeError(
                    "La clave actual del perfil no puede repetirse entre las claves históricas."
                )
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise RuntimeError("Una clave histórica del perfil está vacía o no es texto.")
            keys[version] = cls._decode_key(raw_key.strip(), historical=True)
        return current_version, keys

    @classmethod
    def _load_current_version(cls) -> int:
        configured = os.getenv(cls._KEY_VERSION_ENV, str(cls._DEFAULT_KEY_VERSION)).strip()
        try:
            version = int(configured)
        except ValueError as exc:
            raise RuntimeError("La versión de la clave de cifrado del perfil no es válida.") from exc
        if version <= 0 or str(version) != configured:
            raise RuntimeError("La versión de la clave de cifrado del perfil debe ser un entero positivo.")
        return version

    @classmethod
    def _load_required_key(cls, env_name: str) -> bytes:
        configured = os.getenv(env_name)
        if configured is None or not configured.strip():
            raise RuntimeError("Falta la clave de cifrado del perfil de usuario.")
        return cls._decode_key(configured.strip(), historical=False)

    @classmethod
    def _decode_key(cls, configured: str, *, historical: bool) -> bytes:
        try:
            key = cls._decode_b64(configured)
        except ValueError as exc:
            label = "Una clave histórica" if historical else "La clave de cifrado"
            raise RuntimeError(f"{label} del perfil no tiene formato válido.") from exc
        if len(key) != 32:
            label = "Una clave histórica" if historical else "La clave de cifrado"
            raise RuntimeError(f"{label} del perfil debe contener exactamente 32 bytes.")
        return key

    @staticmethod
    def _associated_data(owner_id: int, key_version: int) -> bytes:
        return f"athena:user-profile:{owner_id}:v{key_version}".encode("ascii")

    @staticmethod
    def _owner_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("owner_user_id interno no válido.")
        return value

    @staticmethod
    def _encode_b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode_b64(value: str) -> bytes:
        try:
            return base64.b64decode(value, altchars=b"-_", validate=True)
        except Exception as exc:
            raise ValueError("Base64 no válido.") from exc
