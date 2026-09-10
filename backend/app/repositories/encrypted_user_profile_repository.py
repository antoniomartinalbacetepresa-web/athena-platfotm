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
    _KEY_VERSION = 1
    _NONCE_BYTES = 12

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._key = self._load_key()
        self._aesgcm = AESGCM(self._key)
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
        key_version = int(row["key_version"])
        if key_version != self._KEY_VERSION:
            raise RuntimeError("Versión de cifrado de perfil no soportada.")
        try:
            nonce = self._decode_b64(str(row["nonce_b64"]))
            ciphertext = self._decode_b64(str(row["ciphertext_b64"]))
            plaintext = self._aesgcm.decrypt(
                nonce,
                ciphertext,
                self._associated_data(owner_id, key_version),
            )
            preferences = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("El perfil cifrado no supera la verificación de integridad.") from exc
        if not isinstance(preferences, dict):
            raise RuntimeError("El perfil cifrado no contiene un objeto válido.")
        return {
            "preferences": preferences,
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    def upsert(self, *, owner_user_id: int, preferences: dict[str, Any]) -> dict[str, Any]:
        owner_id = self._owner_id(owner_user_id)
        if not isinstance(preferences, dict) or not preferences:
            raise ValueError("preferences debe ser un objeto no vacío.")
        plaintext = json.dumps(
            preferences,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        nonce = os.urandom(self._NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(
            nonce,
            plaintext,
            self._associated_data(owner_id, self._KEY_VERSION),
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
                    self._KEY_VERSION,
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

    @classmethod
    def _load_key(cls) -> bytes:
        configured = os.getenv(cls._KEY_ENV)
        if configured is None or not configured.strip():
            raise RuntimeError("Falta la clave de cifrado del perfil de usuario.")
        try:
            key = cls._decode_b64(configured.strip())
        except ValueError as exc:
            raise RuntimeError("La clave de cifrado del perfil no tiene formato válido.") from exc
        if len(key) != 32:
            raise RuntimeError("La clave de cifrado del perfil debe contener exactamente 32 bytes.")
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
