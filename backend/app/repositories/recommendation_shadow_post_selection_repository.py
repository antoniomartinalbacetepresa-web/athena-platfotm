from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowPostSelectionRepository:
    """Persist the first immutable selection instant for a frozen shadow model.

    A post-selection confirmation boundary must be committed before fresh evidence
    is inspected. The model fingerprint is therefore unique: repeated registration
    can only recover the original selection event, never move it backwards or
    forwards after outcomes become visible.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_post_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_fingerprint TEXT NOT NULL UNIQUE,
                    research_cutoff TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    selected_at TEXT NOT NULL,
                    frozen_model_json TEXT NOT NULL,
                    selection_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_post_selection_selected_at
                ON athena_recommendation_shadow_post_selections(selected_at);
                """
            )

    def register(
        self,
        *,
        frozen_model: dict[str, Any],
        selected_at: datetime,
    ) -> dict[str, Any]:
        self.initialize()
        model_fingerprint = self._sha256(
            frozen_model.get("fingerprint"), "model fingerprint"
        )
        research_cutoff = self._aware_iso(
            frozen_model.get("researchCutoff"), "researchCutoff"
        )
        horizon_days = self._positive_int(
            frozen_model.get("horizonDays"), "horizonDays"
        )
        selected = self._aware_datetime(selected_at, "selected_at")
        research_dt = self._parse_iso(research_cutoff, "researchCutoff")
        if selected <= research_dt:
            raise ValueError("selected_at debe ser posterior al researchCutoff.")

        serialized_model = self._serialize(frozen_model)
        selection_core = {
            "modelFingerprint": model_fingerprint,
            "researchCutoff": research_cutoff,
            "horizonDays": horizon_days,
            "selectedAt": selected.isoformat(),
            "frozenModelFingerprint": hashlib.sha256(
                serialized_model.encode("utf-8")
            ).hexdigest(),
        }
        selection_fingerprint = hashlib.sha256(
            self._serialize(selection_core).encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_post_selections (
                    model_fingerprint,
                    research_cutoff,
                    horizon_days,
                    selected_at,
                    frozen_model_json,
                    selection_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_fingerprint,
                    research_cutoff,
                    horizon_days,
                    selected.isoformat(),
                    serialized_model,
                    selection_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_shadow_post_selections
                WHERE model_fingerprint = ?
                """,
                (model_fingerprint,),
            ).fetchone()

        record = self._row(row)
        if record is None:
            raise RuntimeError("No se pudo recuperar la selección shadow registrada.")
        return record

    def get(self, *, model_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(model_fingerprint, "model_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_shadow_post_selections
                WHERE model_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        model = record.get("frozen_model")
        if not isinstance(model, dict):
            raise ValueError("La selección persistida no contiene frozen_model válido.")
        core = {
            "modelFingerprint": self._sha256(
                record.get("model_fingerprint"), "model_fingerprint"
            ),
            "researchCutoff": self._aware_iso(
                record.get("research_cutoff"), "research_cutoff"
            ),
            "horizonDays": self._positive_int(
                record.get("horizon_days"), "horizon_days"
            ),
            "selectedAt": self._aware_iso(record.get("selected_at"), "selected_at"),
            "frozenModelFingerprint": hashlib.sha256(
                self._serialize(model).encode("utf-8")
            ).hexdigest(),
        }
        expected = hashlib.sha256(self._serialize(core).encode("utf-8")).hexdigest()
        actual = self._sha256(
            record.get("selection_fingerprint"), "selection_fingerprint"
        )
        if expected != actual:
            raise ValueError("La selección post-selection fue modificada tras persistirse.")
        if model.get("fingerprint") != core["modelFingerprint"]:
            raise ValueError("La selección no corresponde al fingerprint del modelo congelado.")
        if self._aware_iso(model.get("researchCutoff"), "model researchCutoff") != core[
            "researchCutoff"
        ]:
            raise ValueError("La selección cambió el researchCutoff del modelo congelado.")
        if self._positive_int(model.get("horizonDays"), "model horizonDays") != core[
            "horizonDays"
        ]:
            raise ValueError("La selección cambió el horizonte del modelo congelado.")
        if self._parse_iso(core["selectedAt"], "selectedAt") <= self._parse_iso(
            core["researchCutoff"], "researchCutoff"
        ):
            raise ValueError("selectedAt debe ser posterior al researchCutoff.")
        return record

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            model = json.loads(str(row["frozen_model_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("El frozen_model_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "model_fingerprint": str(row["model_fingerprint"]),
            "research_cutoff": str(row["research_cutoff"]),
            "horizon_days": int(row["horizon_days"]),
            "selected_at": str(row["selected_at"]),
            "frozen_model": model,
            "selection_fingerprint": str(row["selection_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _positive_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return parsed

    def _aware_datetime(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_iso(self, value: str, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_datetime(parsed, field)

    def _aware_iso(self, value: object, field: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        return self._parse_iso(raw, field).isoformat()
