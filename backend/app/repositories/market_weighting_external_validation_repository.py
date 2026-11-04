from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarketWeightingExternalValidationRepository:
    """Append-only external validation evidence for regional market weighting.

    Validation is intentionally offline/human-controlled.  This repository has
    no HTTP write surface and does not activate weighting by itself; readiness
    still depends on every structural gate in MarketWeightingReadinessService.
    """

    _TABLE = "athena_market_weighting_external_validations"

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_table()

    def register(
        self,
        *,
        identity_evidence_fingerprint: str,
        reference: str,
        reviewer_id: str,
        human_review_confirmed: bool,
        validated_at: datetime | None = None,
    ) -> dict[str, Any]:
        evidence_fingerprint = self._sha256(
            identity_evidence_fingerprint,
            "identity_evidence_fingerprint",
        )
        normalized_reference = self._required_text(reference, "reference")
        normalized_reviewer = self._required_text(reviewer_id, "reviewer_id")
        if human_review_confirmed is not True:
            raise ValueError("human_review_confirmed debe ser true.")

        validation_time = self._utc(validated_at or datetime.now(timezone.utc))
        created_time = datetime.now(timezone.utc)
        if validation_time > created_time:
            raise ValueError("validated_at no puede estar en el futuro.")

        core: dict[str, Any] = {
            "status": "external_market_weighting_validation",
            "validationPassed": True,
            "identityEvidenceFingerprint": evidence_fingerprint,
            "reference": normalized_reference,
            "reviewerId": normalized_reviewer,
            "humanReviewConfirmed": True,
            "validationMode": "offline_local_operator",
            "automaticWeightingActivation": False,
            "validatedAt": self._iso(validation_time),
            "createdAt": self._iso(created_time),
        }
        validation_fingerprint = self._fingerprint(core)
        artifact = dict(core)
        artifact["validationFingerprint"] = validation_fingerprint
        payload = self._canonical_json(artifact)

        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    validation_fingerprint,
                    identity_evidence_fingerprint,
                    reference,
                    reviewer_id,
                    human_review_confirmed,
                    validation_passed,
                    validated_at,
                    created_at,
                    validation_json
                ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)
                """,
                (
                    validation_fingerprint,
                    evidence_fingerprint,
                    normalized_reference,
                    normalized_reviewer,
                    artifact["validatedAt"],
                    artifact["createdAt"],
                    payload,
                ),
            )

        return artifact

    def get_latest_for_evidence(
        self,
        *,
        identity_evidence_fingerprint: str,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        evidence_fingerprint = self._sha256(
            identity_evidence_fingerprint,
            "identity_evidence_fingerprint",
        )
        cutoff = self._utc(as_of or datetime.now(timezone.utc))
        cutoff_text = self._iso(cutoff)

        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {self._TABLE}
                WHERE identity_evidence_fingerprint = ?
                  AND validated_at <= ?
                  AND created_at <= ?
                ORDER BY validated_at DESC, id DESC
                LIMIT 1
                """,
                (evidence_fingerprint, cutoff_text, cutoff_text),
            ).fetchone()

        if row is None:
            return None
        return self._validate_record(dict(row), expected_evidence=evidence_fingerprint)

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    validation_fingerprint TEXT NOT NULL UNIQUE,
                    identity_evidence_fingerprint TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    human_review_confirmed INTEGER NOT NULL CHECK (human_review_confirmed = 1),
                    validation_passed INTEGER NOT NULL CHECK (validation_passed = 1),
                    validated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    validation_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_market_weighting_validation_evidence_time
                ON {self._TABLE} (
                    identity_evidence_fingerprint,
                    validated_at,
                    created_at
                );
                """
            )

    def _validate_record(
        self,
        row: dict[str, Any],
        *,
        expected_evidence: str,
    ) -> dict[str, Any]:
        try:
            artifact = json.loads(str(row["validation_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("La evidencia externa persistida no es JSON válido.") from exc
        if not isinstance(artifact, dict):
            raise RuntimeError("La evidencia externa persistida no es un objeto.")

        fingerprint = self._sha256(
            artifact.get("validationFingerprint"),
            "validationFingerprint",
        )
        core = dict(artifact)
        core.pop("validationFingerprint", None)
        if self._fingerprint(core) != fingerprint:
            raise RuntimeError("Fingerprint de validación externa no verificable.")

        checks = {
            "validation_fingerprint": fingerprint,
            "identity_evidence_fingerprint": expected_evidence,
            "reference": self._required_text(artifact.get("reference"), "reference"),
            "reviewer_id": self._required_text(artifact.get("reviewerId"), "reviewerId"),
            "validated_at": self._iso(self._parse_utc(artifact.get("validatedAt"), "validatedAt")),
            "created_at": self._iso(self._parse_utc(artifact.get("createdAt"), "createdAt")),
        }
        for column, expected in checks.items():
            if str(row.get(column)) != expected:
                raise RuntimeError(f"La columna {column} no coincide con el artefacto sellado.")

        if artifact.get("status") != "external_market_weighting_validation":
            raise RuntimeError("Estado de validación externa no soportado.")
        if artifact.get("validationPassed") is not True or int(row["validation_passed"]) != 1:
            raise RuntimeError("La validación externa persistida no está aprobada.")
        if artifact.get("humanReviewConfirmed") is not True or int(row["human_review_confirmed"]) != 1:
            raise RuntimeError("Falta revisión humana verificable.")
        if artifact.get("validationMode") != "offline_local_operator":
            raise RuntimeError("Modo de validación externa no soportado.")
        if artifact.get("automaticWeightingActivation") is not False:
            raise RuntimeError("La validación externa no puede activar pesos automáticamente.")
        if artifact.get("identityEvidenceFingerprint") != expected_evidence:
            raise RuntimeError("La validación externa pertenece a otra evidencia de identidad.")

        return artifact

    def _fingerprint(self, value: dict[str, Any]) -> str:
        return hashlib.sha256(self._canonical_json(value).encode("utf-8")).hexdigest()

    def _canonical_json(self, value: dict[str, Any]) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _required_text(self, value: Any, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: Any, field: str) -> str:
        result = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(result):
            raise ValueError(f"{field} debe ser un SHA-256 válido.")
        return result

    def _utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("La fecha debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_utc(self, value: Any, field: str) -> datetime:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"{field} no es una fecha válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _iso(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
