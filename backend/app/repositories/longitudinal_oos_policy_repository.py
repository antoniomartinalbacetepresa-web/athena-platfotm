from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)


class LongitudinalOosPolicyRepository:
    """Append-only PIT store for longitudinal OOS policy and human approval.

    This repository persists governance evidence only. It never selects policy
    thresholds, approves on behalf of a human, promotes a model, or enables
    trading/production learning.
    """

    _POLICY_TABLE = "athena_longitudinal_oos_policies"
    _APPROVAL_TABLE = "athena_longitudinal_oos_policy_approvals"

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_tables()

    def register_policy(
        self,
        *,
        policy_id: str,
        version: int,
        criteria: dict[str, Any],
        precommitted_by: str,
        evidence_ref: str,
        precommitted_at: datetime | None = None,
    ) -> dict[str, Any]:
        policy_id = self._required_text(policy_id, "policy_id")
        if isinstance(version, bool) or int(version) <= 0 or int(version) != float(version):
            raise ValueError("version debe ser entero positivo.")
        version = int(version)
        precommitted_by = self._required_text(precommitted_by, "precommitted_by")
        evidence_ref = self._required_text(evidence_ref, "evidence_ref")
        when = self._utc(precommitted_at or datetime.now(timezone.utc))
        created = datetime.now(timezone.utc)
        if when > created:
            raise ValueError("precommitted_at no puede estar en el futuro.")

        fingerprint = LongitudinalOosSufficiencyPolicyService.fingerprint(
            policy_id=policy_id,
            version=version,
            criteria=criteria,
        )
        artifact = {
            "module": LongitudinalOosSufficiencyPolicyService.MODULE,
            "policyId": policy_id,
            "version": version,
            "criteria": criteria,
            "policyFingerprint": fingerprint,
            "precommittedBy": precommitted_by,
            "evidenceRef": evidence_ref,
            "precommittedAt": self._iso(when),
            "automaticApproval": False,
            "automaticProductionPromotion": False,
        }
        sealed = self._seal(artifact)
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._POLICY_TABLE} (
                    policy_id, version, policy_fingerprint, precommitted_at,
                    created_at, artifact_json, artifact_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    version,
                    fingerprint,
                    artifact["precommittedAt"],
                    self._iso(created),
                    self._canonical(artifact),
                    sealed,
                ),
            )
        return {"artifact": artifact}

    def approve_policy(
        self,
        *,
        policy_fingerprint: str,
        approved_by: str,
        evidence_ref: str,
        human_review_confirmed: bool,
        approved_at: datetime | None = None,
    ) -> dict[str, Any]:
        fingerprint = self._sha(policy_fingerprint, "policy_fingerprint")
        approved_by = self._required_text(approved_by, "approved_by")
        evidence_ref = self._required_text(evidence_ref, "evidence_ref")
        if human_review_confirmed is not True:
            raise ValueError("human_review_confirmed debe ser true.")
        when = self._utc(approved_at or datetime.now(timezone.utc))
        created = datetime.now(timezone.utc)
        if when > created:
            raise ValueError("approved_at no puede estar en el futuro.")

        policy = self.get_policy_by_fingerprint(policy_fingerprint=fingerprint, as_of=when)
        if policy is None:
            raise ValueError("No existe una política precomprometida visible al approved_at.")
        artifact = {
            "status": "approved",
            "policyFingerprint": fingerprint,
            "approvedBy": approved_by,
            "evidenceRef": evidence_ref,
            "approvedAt": self._iso(when),
            "humanReviewConfirmed": True,
            "approvalMode": "offline_human_operator",
            "automaticApproval": False,
            "automaticProductionPromotion": False,
        }
        sealed = self._seal(artifact)
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._APPROVAL_TABLE} (
                    policy_fingerprint, approved_at, created_at,
                    artifact_json, artifact_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    artifact["approvedAt"],
                    self._iso(created),
                    self._canonical(artifact),
                    sealed,
                ),
            )
        return {"artifact": artifact}

    def get_latest_policy(self, *, as_of: datetime | None = None) -> dict[str, Any] | None:
        cutoff = self._utc(as_of or datetime.now(timezone.utc))
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {self._POLICY_TABLE}
                WHERE precommitted_at <= ? AND created_at <= ?
                ORDER BY precommitted_at DESC, id DESC LIMIT 1
                """,
                (self._iso(cutoff), self._iso(cutoff)),
            ).fetchone()
        return self._policy_record(dict(row)) if row is not None else None

    def get_policy_by_fingerprint(
        self, *, policy_fingerprint: str, as_of: datetime | None = None
    ) -> dict[str, Any] | None:
        fingerprint = self._sha(policy_fingerprint, "policy_fingerprint")
        cutoff = self._utc(as_of or datetime.now(timezone.utc))
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {self._POLICY_TABLE}
                WHERE policy_fingerprint = ?
                  AND precommitted_at <= ? AND created_at <= ?
                ORDER BY id DESC LIMIT 1
                """,
                (fingerprint, self._iso(cutoff), self._iso(cutoff)),
            ).fetchone()
        return self._policy_record(dict(row)) if row is not None else None

    def get_latest_approval(
        self, *, policy_fingerprint: str, as_of: datetime | None = None
    ) -> dict[str, Any] | None:
        fingerprint = self._sha(policy_fingerprint, "policy_fingerprint")
        cutoff = self._utc(as_of or datetime.now(timezone.utc))
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {self._APPROVAL_TABLE}
                WHERE policy_fingerprint = ?
                  AND approved_at <= ? AND created_at <= ?
                ORDER BY approved_at DESC, id DESC LIMIT 1
                """,
                (fingerprint, self._iso(cutoff), self._iso(cutoff)),
            ).fetchone()
        return self._approval_record(dict(row), fingerprint) if row is not None else None

    def _policy_record(self, row: dict[str, Any]) -> dict[str, Any]:
        artifact = self._decode_and_verify(row)
        fingerprint = self._sha(artifact.get("policyFingerprint"), "policyFingerprint")
        expected = LongitudinalOosSufficiencyPolicyService.fingerprint(
            policy_id=str(artifact.get("policyId", "")),
            version=int(artifact.get("version", 0)),
            criteria=artifact.get("criteria") if isinstance(artifact.get("criteria"), dict) else {},
        )
        if fingerprint != expected or str(row.get("policy_fingerprint")) != fingerprint:
            raise RuntimeError("La política persistida no coincide con su fingerprint canónico.")
        if artifact.get("automaticApproval") is not False or artifact.get("automaticProductionPromotion") is not False:
            raise RuntimeError("La política persistida contiene automatización prohibida.")
        return {"artifact": artifact}

    def _approval_record(self, row: dict[str, Any], expected_fingerprint: str) -> dict[str, Any]:
        artifact = self._decode_and_verify(row)
        if artifact.get("status") != "approved":
            raise RuntimeError("Estado de aprobación longitudinal no soportado.")
        if artifact.get("humanReviewConfirmed") is not True:
            raise RuntimeError("Falta revisión humana verificable.")
        if artifact.get("approvalMode") != "offline_human_operator":
            raise RuntimeError("Modo de aprobación longitudinal no soportado.")
        if artifact.get("automaticApproval") is not False or artifact.get("automaticProductionPromotion") is not False:
            raise RuntimeError("La aprobación persistida contiene automatización prohibida.")
        if self._sha(artifact.get("policyFingerprint"), "policyFingerprint") != expected_fingerprint:
            raise RuntimeError("La aprobación pertenece a otra política.")
        return {"artifact": artifact}

    def _decode_and_verify(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Artefacto longitudinal persistido inválido.") from exc
        if not isinstance(artifact, dict):
            raise RuntimeError("Artefacto longitudinal persistido no es objeto.")
        if self._seal(artifact) != str(row.get("artifact_hash")):
            raise RuntimeError("Artefacto longitudinal persistido fue alterado.")
        return artifact

    def _ensure_tables(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._POLICY_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    policy_fingerprint TEXT NOT NULL UNIQUE,
                    precommitted_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    UNIQUE(policy_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_longitudinal_oos_policy_pit
                ON {self._POLICY_TABLE}(precommitted_at, created_at);

                CREATE TABLE IF NOT EXISTS {self._APPROVAL_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_fingerprint TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(policy_fingerprint)
                        REFERENCES {self._POLICY_TABLE}(policy_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_longitudinal_oos_approval_pit
                ON {self._APPROVAL_TABLE}(policy_fingerprint, approved_at, created_at);
                """
            )

    def _seal(self, artifact: dict[str, Any]) -> str:
        return hashlib.sha256(self._canonical(artifact).encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _sha(value: Any, field: str) -> str:
        text = str(value or "").strip().lower()
        if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return text

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("La fecha debe incluir timezone.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
