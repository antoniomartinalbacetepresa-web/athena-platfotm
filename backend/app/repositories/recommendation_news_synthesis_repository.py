from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PROVIDER_TOKENS = ("financialmodelingprep", "fmp")


class RecommendationNewsSynthesisRepository:
    """Append-only persistence for one canonical News synthesis per research cycle."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_news_syntheses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_hash TEXT NOT NULL UNIQUE,
                    radar_hash TEXT NOT NULL,
                    synthesis_hash TEXT NOT NULL UNIQUE,
                    package_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_athena_news_synthesis_hash
                ON athena_news_syntheses(synthesis_hash);
                """
            )

    def append(self, *, cycle_hash: str, radar_hash: str, synthesis_payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        package = self.validate_package(cycle_hash=cycle_hash, radar_hash=radar_hash, synthesis_payload=synthesis_payload)
        synthesis_hash = self._canonical_hash(package)
        serialized = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now().astimezone().isoformat()
        with self._database.connect() as connection:
            existing = connection.execute("SELECT * FROM athena_news_syntheses WHERE cycle_hash = ?", (package["cycleHash"],)).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["synthesis_hash"] != synthesis_hash:
                    raise ValueError("El Research Cycle ya tiene una síntesis News distinta; la selección retrospectiva de salidas de modelo está prohibida.")
                return record
            connection.execute("INSERT INTO athena_news_syntheses (cycle_hash, radar_hash, synthesis_hash, package_json, created_at) VALUES (?, ?, ?, ?, ?)", (package["cycleHash"], package["radarHash"], synthesis_hash, serialized, created_at))
            row = connection.execute("SELECT * FROM athena_news_syntheses WHERE synthesis_hash = ?", (synthesis_hash,)).fetchone()
        return self.validate_record(self._row(row))

    def get_by_cycle_hash(self, *, cycle_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(cycle_hash, "cycle_hash")
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM athena_news_syntheses WHERE cycle_hash = ?", (normalized,)).fetchone()
        if row is None:
            raise ValueError("El Research Cycle no tiene síntesis News persistida.")
        return self.validate_record(self._row(row))

    def get_latest(self) -> dict[str, Any]:
        """Return the newest persisted synthesis only after canonical integrity validation."""
        self.initialize()
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM athena_news_syntheses ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError("No existe ninguna síntesis News persistida.")
        selected = self.validate_record(self._row(row))
        # Re-read through the canonical lookup so latest selection cannot bypass
        # the same cycle-hash and package-integrity boundary used elsewhere.
        return self.get_by_cycle_hash(cycle_hash=selected["cycle_hash"])

    def validate_package(self, *, cycle_hash: str, radar_hash: str, synthesis_payload: dict[str, Any]) -> dict[str, Any]:
        normalized_cycle = self._sha256(cycle_hash, "cycle_hash")
        normalized_radar = self._sha256(radar_hash, "radar_hash")
        if not isinstance(synthesis_payload, dict): raise ValueError("synthesis_payload debe ser un objeto.")
        if synthesis_payload.get("status") != "validated_external_model_output": raise ValueError("La síntesis News perdió su estado validado.")
        for field in ("modelExecutionVerified", "productionTruthClaimed", "independentCorroborationClaimed", "recommendationInfluence", "automaticScoring", "automaticTrading"):
            if synthesis_payload.get(field) is not False: raise ValueError(f"La síntesis News debe mantener {field}=false.")
        assessed_count = self._nonnegative_int(synthesis_payload.get("assessedCount"), "assessedCount")
        included_count = self._nonnegative_int(synthesis_payload.get("includedCount"), "includedCount")
        excluded_count = self._nonnegative_int(synthesis_payload.get("excludedCount"), "excludedCount")
        assessments = synthesis_payload.get("assessments"); items = synthesis_payload.get("items")
        if not isinstance(assessments, list) or not assessments: raise ValueError("La síntesis News debe conservar assessments completos.")
        if not isinstance(items, list): raise ValueError("La síntesis News debe conservar items filtrados.")
        if assessed_count != len(assessments): raise ValueError("assessedCount no coincide con assessments.")
        if included_count != len(items): raise ValueError("includedCount no coincide con items.")
        if excluded_count != assessed_count - included_count: raise ValueError("excludedCount no reconcilia con assessedCount e includedCount.")
        assessment_ids: set[str] = set(); assessment_fingerprints: set[str] = set()
        for assessment in assessments:
            if not isinstance(assessment, dict): raise ValueError("Cada assessment persistido debe ser un objeto.")
            evidence_id = self._required_text(assessment.get("evidenceId"), "assessment.evidenceId")
            if evidence_id in assessment_ids: raise ValueError("assessment.evidenceId no puede repetirse.")
            assessment_ids.add(evidence_id); self._sha256(assessment.get("inputFingerprint"), "assessment.inputFingerprint")
            fingerprint = self._sha256(assessment.get("assessmentFingerprint"), "assessment.assessmentFingerprint")
            if fingerprint in assessment_fingerprints: raise ValueError("assessmentFingerprint no puede repetirse.")
            assessment_fingerprints.add(fingerprint); self._https(assessment.get("sourceRef"), "assessment.sourceRef")
            self._assert_provider_allowed(self._required_text(assessment.get("modelProvider"), "assessment.modelProvider")); self._assert_provider_allowed(self._required_text(assessment.get("evidenceProvider"), "assessment.evidenceProvider"))
        item_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict): raise ValueError("Cada item persistido debe ser un objeto.")
            evidence_id = self._required_text(item.get("evidenceId"), "item.evidenceId")
            if evidence_id in item_ids: raise ValueError("item.evidenceId no puede repetirse.")
            if evidence_id not in assessment_ids: raise ValueError("items debe ser subconjunto de assessments.")
            item_ids.add(evidence_id); matching = next(a for a in assessments if a.get("evidenceId") == evidence_id)
            if item != matching: raise ValueError("Cada item filtrado debe coincidir exactamente con su assessment.")
        return {"cycleHash": normalized_cycle, "radarHash": normalized_radar, "synthesis": synthesis_payload}

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict): raise ValueError("El registro persistido de síntesis debe ser un objeto.")
        package = record.get("package")
        if not isinstance(package, dict): raise ValueError("La síntesis persistida carece de package válido.")
        validated = self.validate_package(cycle_hash=package.get("cycleHash"), radar_hash=package.get("radarHash"), synthesis_payload=package.get("synthesis"))
        expected_hash = self._canonical_hash(validated)
        if self._sha256(record.get("synthesis_hash"), "synthesis_hash") != expected_hash: raise ValueError("synthesis_hash no coincide con el package persistido.")
        if record.get("cycle_hash") != validated["cycleHash"]: raise ValueError("cycle_hash persistido no coincide con el package.")
        if record.get("radar_hash") != validated["radarHash"]: raise ValueError("radar_hash persistido no coincide con el package.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None: raise RuntimeError("No se pudo recuperar la síntesis News persistida.")
        try: package = json.loads(str(row["package_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc: raise ValueError("package_json de síntesis no es JSON válido.") from exc
        return {"id": int(row["id"]), "cycle_hash": str(row["cycle_hash"]), "radar_hash": str(row["radar_hash"]), "synthesis_hash": str(row["synthesis_hash"]), "package": package, "created_at": str(row["created_at"])}

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text: raise ValueError(f"{field} es obligatorio.")
        return text
    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text): raise ValueError(f"{field} debe ser un SHA-256 hexadecimal válido.")
        return text
    def _nonnegative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ValueError(f"{field} debe ser un entero no negativo.")
        return value
    def _https(self, value: object, field: str) -> str:
        text = self._required_text(value, field); parsed = urlparse(text)
        if parsed.scheme.casefold() != "https" or not parsed.netloc: raise ValueError(f"{field} debe ser una URL HTTPS absoluta.")
        return text
    def _assert_provider_allowed(self, provider: str) -> None:
        compact = "".join(ch for ch in provider.casefold() if ch.isalnum())
        if any(token in compact for token in _FORBIDDEN_PROVIDER_TOKENS): raise ValueError("FMP/Financial Modeling Prep está prohibido en síntesis News.")
