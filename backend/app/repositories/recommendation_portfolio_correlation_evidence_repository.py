from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationPortfolioCorrelationEvidenceRepository:
    """Append-only authority for PIT portfolio-correlation evidence."""

    ARTIFACT_VERSION = "athena-portfolio-correlation-evidence-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_portfolio_correlation_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_fingerprint TEXT NOT NULL UNIQUE,
                    left_instrument_id INTEGER NOT NULL,
                    right_instrument_id INTEGER NOT NULL,
                    source_provider TEXT NOT NULL,
                    knowledge_cutoff TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_correlation_pair
                ON athena_recommendation_portfolio_correlation_evidence(
                    left_instrument_id,
                    right_instrument_id,
                    knowledge_cutoff
                );
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self.validate_artifact(artifact)
        evidence_fingerprint = self._sha256(
            validated.get("portfolioCorrelationEvidenceFingerprint"),
            "portfolioCorrelationEvidenceFingerprint",
        )
        left = self._positive_int(validated.get("leftInstrumentId"), "leftInstrumentId")
        right = self._positive_int(validated.get("rightInstrumentId"), "rightInstrumentId")
        provider = self._text(validated.get("sourceProvider"), "sourceProvider")
        cutoff = self._aware_iso(validated.get("knowledgeCutoff"), "knowledgeCutoff").isoformat()
        serialized = self._serialize(validated)

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_portfolio_correlation_evidence
                WHERE evidence_fingerprint = ?
                """,
                (evidence_fingerprint,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la correlación persistida.")
                if record["artifact"] != validated:
                    raise ValueError("La evidencia de correlación es inmutable.")
                return record

            persisted_at = datetime.now(timezone.utc).isoformat()
            core = {
                "evidenceFingerprint": evidence_fingerprint,
                "leftInstrumentId": left,
                "rightInstrumentId": right,
                "sourceProvider": provider,
                "knowledgeCutoff": cutoff,
                "artifact": validated,
                "persistedAt": persisted_at,
            }
            record_fingerprint = self._fingerprint(core)
            connection.execute(
                """
                INSERT INTO athena_recommendation_portfolio_correlation_evidence (
                    evidence_fingerprint,
                    left_instrument_id,
                    right_instrument_id,
                    source_provider,
                    knowledge_cutoff,
                    artifact_json,
                    persisted_at,
                    record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_fingerprint,
                    left,
                    right,
                    provider,
                    cutoff,
                    serialized,
                    persisted_at,
                    record_fingerprint,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_portfolio_correlation_evidence
                WHERE evidence_fingerprint = ?
                """,
                (evidence_fingerprint,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la correlación persistida.")
        return result

    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(evidence_fingerprint, "evidence_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_portfolio_correlation_evidence
                WHERE evidence_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de correlación debe ser un objeto.")
        evidence_fp = self._sha256(record.get("evidence_fingerprint"), "evidence_fingerprint")
        left = self._positive_int(record.get("left_instrument_id"), "left_instrument_id")
        right = self._positive_int(record.get("right_instrument_id"), "right_instrument_id")
        provider = self._text(record.get("source_provider"), "source_provider")
        cutoff = self._aware_iso(record.get("knowledge_cutoff"), "knowledge_cutoff").isoformat()
        persisted_at = self._aware_iso(record.get("persisted_at"), "persisted_at").isoformat()
        artifact = self.validate_artifact(record.get("artifact"))
        if artifact.get("portfolioCorrelationEvidenceFingerprint") != evidence_fp:
            raise ValueError("El registro cambió el fingerprint de correlación.")
        if self._positive_int(artifact.get("leftInstrumentId"), "artifact.leftInstrumentId") != left:
            raise ValueError("El registro cambió leftInstrumentId.")
        if self._positive_int(artifact.get("rightInstrumentId"), "artifact.rightInstrumentId") != right:
            raise ValueError("El registro cambió rightInstrumentId.")
        if self._text(artifact.get("sourceProvider"), "artifact.sourceProvider") != provider:
            raise ValueError("El registro cambió sourceProvider.")
        if self._aware_iso(artifact.get("knowledgeCutoff"), "artifact.knowledgeCutoff").isoformat() != cutoff:
            raise ValueError("El registro cambió knowledgeCutoff.")
        supplied = self._sha256(record.get("record_fingerprint"), "record_fingerprint")
        core = {
            "evidenceFingerprint": evidence_fp,
            "leftInstrumentId": left,
            "rightInstrumentId": right,
            "sourceProvider": provider,
            "knowledgeCutoff": cutoff,
            "artifact": artifact,
            "persistedAt": persisted_at,
        }
        if self._fingerprint(core) != supplied:
            raise ValueError("El registro de correlación fue modificado.")
        return record

    def validate_artifact(self, artifact: object) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("La evidencia de correlación debe ser un objeto.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de evidencia de correlación no soportada.")
        if artifact.get("status") != "portfolio_correlation_evidence_verified_non_advisory":
            raise ValueError("Estado de correlación no soportado.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La correlación intentó emitir advice.")
        for field in ("productionEligible", "allocationEligible", "automaticTrading"):
            if artifact.get(field) is not False:
                raise ValueError(f"La correlación violó {field}=False.")
        left = self._positive_int(artifact.get("leftInstrumentId"), "leftInstrumentId")
        right = self._positive_int(artifact.get("rightInstrumentId"), "rightInstrumentId")
        if left == right:
            raise ValueError("La correlación requiere instrumentos distintos.")
        self._text(artifact.get("sourceProvider"), "sourceProvider")
        cutoff = self._aware_iso(artifact.get("knowledgeCutoff"), "knowledgeCutoff")
        latest = self._aware_iso(artifact.get("latestRetrievedAt"), "latestRetrievedAt")
        if latest > cutoff:
            raise ValueError("La correlación contiene datos recuperados después del cutoff.")
        self._positive_int(artifact.get("sampleCount"), "sampleCount")
        correlation = self._finite(artifact.get("correlation"), "correlation")
        if correlation < -1.0 or correlation > 1.0:
            raise ValueError("La correlación está fuera de [-1,1].")
        self._date_text(artifact.get("firstReturnDate"), "firstReturnDate")
        self._date_text(artifact.get("lastReturnDate"), "lastReturnDate")
        if artifact.get("priceField") != "adjusted_close":
            raise ValueError("La correlación debe usar adjusted_close.")
        core_keys = (
            "artifactVersion",
            "leftInstrumentId",
            "rightInstrumentId",
            "sourceProvider",
            "knowledgeCutoff",
            "sampleCount",
            "correlation",
            "firstReturnDate",
            "lastReturnDate",
            "latestRetrievedAt",
            "priceField",
            "alignmentPolicy",
            "returnPolicy",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(
            artifact.get("portfolioCorrelationEvidenceFingerprint"),
            "portfolioCorrelationEvidenceFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La evidencia de correlación fue modificada.")
        self._assert_finite(artifact)
        return artifact

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de correlación no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "evidence_fingerprint": str(row["evidence_fingerprint"]),
            "left_instrument_id": int(row["left_instrument_id"]),
            "right_instrument_id": int(row["right_instrument_id"]),
            "source_provider": str(row["source_provider"]),
            "knowledge_cutoff": str(row["knowledge_cutoff"]),
            "artifact": artifact,
            "persisted_at": str(row["persisted_at"]),
            "record_fingerprint": str(row["record_fingerprint"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("La correlación contiene datos no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _aware_iso(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser fecha ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha ISO válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _date_text(self, value: object, field: str) -> str:
        text = self._text(value, field)
        try:
            datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha válida.") from exc
        return text

    def _assert_finite(self, value: object) -> None:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("La correlación contiene valores no finitos.")
            return
        if isinstance(value, dict):
            for item in value.values():
                self._assert_finite(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_finite(item)
