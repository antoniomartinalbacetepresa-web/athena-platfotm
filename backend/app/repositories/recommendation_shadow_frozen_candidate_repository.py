from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowFrozenCandidateRepository:
    """Persist immutable research-only frozen candidate bundles.

    This table is intentionally separate from user-facing recommendations and
    contains no action, score or conviction columns. The bundle fingerprint is
    unique so repeated persistence of the same validated artifact is idempotent.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_frozen_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bundle_fingerprint TEXT NOT NULL UNIQUE,
                    model_fingerprint TEXT NOT NULL,
                    research_gate_fingerprint TEXT NOT NULL,
                    protocol_selection_fingerprint TEXT NOT NULL,
                    source_walk_forward_fingerprint TEXT NOT NULL,
                    bundle_version TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
                    research_cutoff TEXT NOT NULL,
                    ridge_lambda REAL NOT NULL CHECK (ridge_lambda >= 0),
                    bundle_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_frozen_cutoff_horizon
                ON athena_recommendation_shadow_frozen_candidates(
                    research_cutoff,
                    horizon_days
                );
                """
            )

    def save(self, *, bundle: dict[str, Any]) -> int:
        self.initialize()
        if bundle.get("status") != "shadow_research_gated_model_frozen":
            raise ValueError("Sólo se pueden persistir bundles gated freeze válidos.")
        if bundle.get("productionEligible") is not False:
            raise ValueError("Un frozen candidate shadow debe mantener productionEligible=False.")
        if bundle.get("advisoryStatus") != "no_advice":
            raise ValueError("Un frozen candidate shadow debe mantener advisoryStatus=no_advice.")

        bundle_fingerprint = self._fingerprint(bundle, "bundleFingerprint")
        model_fingerprint = self._required_text(bundle.get("modelFingerprint"), "modelFingerprint")
        gate_fingerprint = self._fingerprint(bundle, "researchGateFingerprint")
        selection_fingerprint = self._fingerprint(bundle, "protocolSelectionFingerprint")
        source_fingerprint = self._fingerprint(bundle, "sourceWalkForwardFingerprint")
        bundle_version = self._required_text(bundle.get("bundleVersion"), "bundleVersion")
        horizon_days = self._positive_int(bundle.get("horizonDays"), "horizonDays")
        research_cutoff = self._aware_iso(bundle.get("researchCutoff"), "researchCutoff")
        ridge_lambda = self._finite_non_negative(bundle.get("ridgeLambda"), "ridgeLambda")

        serialized = json.dumps(
            bundle,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_frozen_candidates (
                    bundle_fingerprint,
                    model_fingerprint,
                    research_gate_fingerprint,
                    protocol_selection_fingerprint,
                    source_walk_forward_fingerprint,
                    bundle_version,
                    horizon_days,
                    research_cutoff,
                    ridge_lambda,
                    bundle_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle_fingerprint,
                    model_fingerprint,
                    gate_fingerprint,
                    selection_fingerprint,
                    source_fingerprint,
                    bundle_version,
                    horizon_days,
                    research_cutoff,
                    ridge_lambda,
                    serialized,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT id, bundle_json
                FROM athena_recommendation_shadow_frozen_candidates
                WHERE bundle_fingerprint = ?
                """,
                (bundle_fingerprint,),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo persistir el frozen candidate shadow.")
        if str(row["bundle_json"]) != serialized:
            raise ValueError(
                "El bundleFingerprint ya existe asociado a contenido diferente."
            )
        return int(row["id"])

    def get_by_fingerprint(self, bundle_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._required_text(bundle_fingerprint, "bundle_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_frozen_candidates
                WHERE bundle_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def list_for_horizon(self, *, horizon_days: int) -> list[dict[str, Any]]:
        self.initialize()
        horizon = self._positive_int(horizon_days, "horizon_days")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_frozen_candidates
                WHERE horizon_days = ?
                ORDER BY research_cutoff, id
                """,
                (horizon,),
            ).fetchall()
        return [self._row(row) for row in rows if row is not None]

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["bundle"] = json.loads(result.pop("bundle_json"))
        return result

    def _fingerprint(self, bundle: dict[str, Any], field: str) -> str:
        value = self._required_text(bundle.get(field), field)
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return value.lower()

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _positive_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return parsed

    def _finite_non_negative(self, value: object, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{field} debe ser finito y no negativo.")
        return parsed

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
