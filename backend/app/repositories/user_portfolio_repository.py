from __future__ import annotations

import base64
import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.database.athena_database import AthenaDatabase


class UserPortfolioRepository:
    """Persist authenticated-user holdings with encrypted sensitive cost basis.

    Ownership is always supplied by trusted backend code. Symbol, exchange and
    quantity remain queryable portfolio state. The optional declared average
    purchase price is sensitive and is therefore stored only as AES-256-GCM
    ciphertext bound to the owner and position identity.
    """

    _TABLE = "athena_user_portfolio_positions"
    _KEY_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY"
    _KEY_VERSION_ENV = "ATHENA_PROFILE_ENCRYPTION_KEY_VERSION"
    _PREVIOUS_KEYS_ENV = "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS"
    _DEFAULT_KEY_VERSION = 1
    _NONCE_BYTES = 12

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_table()

    def list_for_owner(self, owner_user_id: int) -> list[dict[str, Any]]:
        owner_id = self._owner_id(owner_user_id)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, symbol, exchange, quantity,
                       average_purchase_price_key_version,
                       average_purchase_price_nonce_b64,
                       average_purchase_price_ciphertext_b64,
                       created_at, updated_at
                FROM {self._TABLE}
                WHERE owner_user_id = ?
                ORDER BY symbol ASC, exchange ASC, id ASC
                """,
                (owner_id,),
            ).fetchall()
        return [self._public_row(owner_id=owner_id, row=dict(row)) for row in rows]

    def upsert(
        self,
        *,
        owner_user_id: int,
        symbol: str,
        exchange: str | None,
        quantity: float,
        average_purchase_price: float | None = None,
    ) -> dict[str, Any]:
        owner_id = self._owner_id(owner_user_id)
        normalized_symbol = self._symbol(symbol)
        normalized_exchange = self._exchange(exchange)
        normalized_quantity = self._quantity(quantity)
        encrypted_price = self._encrypt_average_purchase_price(
            owner_id=owner_id,
            symbol=normalized_symbol,
            exchange=normalized_exchange,
            value=average_purchase_price,
        )
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    owner_user_id, symbol, exchange, quantity,
                    average_purchase_price_key_version,
                    average_purchase_price_nonce_b64,
                    average_purchase_price_ciphertext_b64,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, symbol, exchange)
                DO UPDATE SET
                    quantity = excluded.quantity,
                    average_purchase_price_key_version = COALESCE(
                        excluded.average_purchase_price_key_version,
                        {self._TABLE}.average_purchase_price_key_version
                    ),
                    average_purchase_price_nonce_b64 = COALESCE(
                        excluded.average_purchase_price_nonce_b64,
                        {self._TABLE}.average_purchase_price_nonce_b64
                    ),
                    average_purchase_price_ciphertext_b64 = COALESCE(
                        excluded.average_purchase_price_ciphertext_b64,
                        {self._TABLE}.average_purchase_price_ciphertext_b64
                    ),
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    normalized_symbol,
                    normalized_exchange,
                    normalized_quantity,
                    encrypted_price[0],
                    encrypted_price[1],
                    encrypted_price[2],
                    now,
                    now,
                ),
            )
            row = connection.execute(
                f"""
                SELECT id, symbol, exchange, quantity,
                       average_purchase_price_key_version,
                       average_purchase_price_nonce_b64,
                       average_purchase_price_ciphertext_b64,
                       created_at, updated_at
                FROM {self._TABLE}
                WHERE owner_user_id = ? AND symbol = ? AND exchange = ?
                LIMIT 1
                """,
                (owner_id, normalized_symbol, normalized_exchange),
            ).fetchone()

        if row is None:
            raise RuntimeError("La posición no pudo recuperarse tras persistirla.")
        return self._public_row(owner_id=owner_id, row=dict(row))

    def delete_for_owner(self, *, owner_user_id: int, position_id: int) -> bool:
        owner_id = self._owner_id(owner_user_id)
        if isinstance(position_id, bool) or not isinstance(position_id, int) or position_id <= 0:
            return False
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {self._TABLE} WHERE id = ? AND owner_user_id = ?",
                (position_id, owner_id),
            )
        return cursor.rowcount == 1

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    average_purchase_price_key_version INTEGER,
                    average_purchase_price_nonce_b64 TEXT,
                    average_purchase_price_ciphertext_b64 TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id)
                        REFERENCES athena_user_accounts(id)
                        ON DELETE CASCADE,
                    UNIQUE (owner_user_id, symbol, exchange)
                );

                CREATE INDEX IF NOT EXISTS idx_athena_user_portfolio_owner
                ON {self._TABLE} (owner_user_id, symbol, exchange);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({self._TABLE})").fetchall()
            }
            migrations = {
                "average_purchase_price_key_version": "INTEGER",
                "average_purchase_price_nonce_b64": "TEXT",
                "average_purchase_price_ciphertext_b64": "TEXT",
            }
            for column, sql_type in migrations.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE {self._TABLE} ADD COLUMN {column} {sql_type}"
                    )

    def _encrypt_average_purchase_price(
        self,
        *,
        owner_id: int,
        symbol: str,
        exchange: str,
        value: float | None,
    ) -> tuple[int | None, str | None, str | None]:
        if value is None:
            return None, None, None
        normalized = self._average_purchase_price(value)
        key_version, keys = self._load_keyring()
        nonce = os.urandom(self._NONCE_BYTES)
        plaintext = json.dumps(
            {"averagePurchasePrice": normalized},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        ciphertext = AESGCM(keys[key_version]).encrypt(
            nonce,
            plaintext,
            self._associated_data(owner_id, symbol, exchange, key_version),
        )
        return key_version, self._encode_b64(nonce), self._encode_b64(ciphertext)

    def _decrypt_average_purchase_price(
        self,
        *,
        owner_id: int,
        row: dict[str, Any],
    ) -> float | None:
        raw_version = row.get("average_purchase_price_key_version")
        raw_nonce = row.get("average_purchase_price_nonce_b64")
        raw_ciphertext = row.get("average_purchase_price_ciphertext_b64")
        if raw_version is None and raw_nonce is None and raw_ciphertext is None:
            return None
        if raw_version is None or raw_nonce is None or raw_ciphertext is None:
            raise RuntimeError("El precio medio cifrado está incompleto.")
        key_version = int(raw_version)
        _, keys = self._load_keyring()
        key = keys.get(key_version)
        if key is None:
            raise RuntimeError(
                f"La clave de cifrado de cartera para la versión {key_version} no está disponible."
            )
        symbol = str(row["symbol"])
        exchange = str(row["exchange"])
        try:
            plaintext = AESGCM(key).decrypt(
                self._decode_b64(str(raw_nonce)),
                self._decode_b64(str(raw_ciphertext)),
                self._associated_data(owner_id, symbol, exchange, key_version),
            )
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid encrypted payload")
            return self._average_purchase_price(payload["averagePurchasePrice"])
        except (InvalidTag, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("El precio medio cifrado no supera la verificación de integridad.") from exc

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
                raise RuntimeError("La clave actual no puede repetirse entre las claves históricas.")
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise RuntimeError("Una clave histórica del perfil está vacía o no es texto.")
            keys[version] = cls._decode_key(raw_key.strip())
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
        return cls._decode_key(configured.strip())

    @classmethod
    def _decode_key(cls, configured: str) -> bytes:
        try:
            key = cls._decode_b64(configured)
        except ValueError as exc:
            raise RuntimeError("La clave de cifrado del perfil no tiene formato válido.") from exc
        if len(key) != 32:
            raise RuntimeError("La clave de cifrado del perfil debe contener exactamente 32 bytes.")
        return key

    @staticmethod
    def _associated_data(owner_id: int, symbol: str, exchange: str, key_version: int) -> bytes:
        return f"athena:user-portfolio:{owner_id}:{symbol}:{exchange}:v{key_version}".encode("utf-8")

    @staticmethod
    def _owner_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("owner_user_id interno no válido.")
        return value

    @staticmethod
    def _symbol(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized or len(normalized) > 32:
            raise ValueError("symbol no válido.")
        return normalized

    @staticmethod
    def _exchange(value: str | None) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) > 32:
            raise ValueError("exchange no válido.")
        return normalized

    @staticmethod
    def _quantity(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quantity debe ser numérica y positiva.")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError("quantity debe ser un número finito positivo.")
        if normalized <= 0 or normalized > 1_000_000_000_000:
            raise ValueError("quantity debe ser positiva y estar dentro del límite operativo.")
        return normalized

    @staticmethod
    def _average_purchase_price(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("average_purchase_price debe ser numérico y positivo.")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized <= 0 or normalized > 1_000_000_000_000:
            raise ValueError("average_purchase_price debe ser finito, positivo y estar dentro del límite operativo.")
        return normalized

    def _public_row(self, *, owner_id: int, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "symbol": str(row["symbol"]),
            "exchange": str(row["exchange"]) or None,
            "quantity": float(row["quantity"]),
            "averagePurchasePrice": self._decrypt_average_purchase_price(
                owner_id=owner_id,
                row=row,
            ),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    @staticmethod
    def _encode_b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode_b64(value: str) -> bytes:
        try:
            return base64.b64decode(value, altchars=b"-_", validate=True)
        except Exception as exc:
            raise ValueError("Base64 no válido.") from exc
