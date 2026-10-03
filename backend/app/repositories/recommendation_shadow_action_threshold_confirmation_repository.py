from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowActionThresholdConfirmationRepository:
    """Persist the first sufficiently mature future-threshold evaluation."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_action_threshold_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    selection_fingerprint TEXT NOT NULL UNIQUE,
                    sealed_at TEXT NOT NULL,
                    confirmation_json TEXT NOT NULL,
                    confirmation_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_action_threshold_confirmation_sealed_at
                ON athena_recommendation_shadow_action_threshold_confirmations(sealed_at);
                """
            )

    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(selection_fingerprint, "selection_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_action_threshold_confirmations
                WHERE selection_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def seal(
        self,
        *,
        selection_fingerprint: str,
        confirmation: dict[str, Any],
        sealed_at: datetime,
    ) -> dict[str, Any]:
        self.initialize()
        fingerprint = self._sha256(selection_fingerprint, "selection_fingerprint")
        sealed = self._aware_datetime(sealed_at, "sealed_at").isoformat()
        serialized = self._serialize(confirmation)
        confirmation_fingerprint = hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()
        created = datetime.now(timezone.utc).isoformat()

        if confirmation.get("selectionFingerprint") != fingerprint:
            raise ValueError("La confirmación no pertenece a la selección suministrada.")

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_action_threshold_confirmations (
                    selection_fingerprint,
                    sealed_at,
                    confirmation_json,
                    confirmation_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    sealed,
                    serialized,
                    confirmation_fingerprint,
                    created,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_action_threshold_confirmations
                WHERE selection_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la confirmación sellada.")
        return result

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de confirmación debe ser un objeto.")
        selection_fingerprint = self._sha256(
            record.get("selection_fingerprint"), "selection_fingerprint"
        )
        self._aware_iso(record.get("sealed_at"), "sealed_at")
        confirmation = record.get("confirmation")
        if not isinstance(confirmation, dict):
            raise ValueError("El registro carece de confirmation válida.")
        if confirmation.get("selectionFingerprint") != selection_fingerprint:
            raise ValueError("La confirmación persistida cambió de selección.")
        actual = self._sha256(
            record.get("confirmation_fingerprint"), "confirmation_fingerprint"
        )
        expected = hashlib.sha256(
            self._serialize(confirmation).encode("utf-8")
        ).hexdigest()
        if actual != expected:
            raise ValueError("La confirmación fue modificada después de persistirse.")
        return record

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            confirmation = json.loads(str(row["confirmation_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("confirmation_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "selection_fingerprint": str(row["selection_fingerprint"]),
            "sealed_at": str(row["sealed_at"]),
            "confirmation": confirmation,
            "confirmation_fingerprint": str(row["confirmation_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _aware_datetime(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _aware_iso(self, value: object, field: str) -> str:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_datetime(parsed, field).isoformat()
