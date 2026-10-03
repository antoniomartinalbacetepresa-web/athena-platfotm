from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationInvestorsSynthesisRepository:
    """Append-only persistence for one canonical Investors synthesis per cycle."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS athena_investors_syntheses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_hash TEXT NOT NULL UNIQUE,
                    radar_hash TEXT NOT NULL,
                    synthesis_hash TEXT NOT NULL UNIQUE,
                    package_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_athena_investors_synthesis_hash
                ON athena_investors_syntheses(synthesis_hash);
            """)

    def append(self, *, cycle_hash: str, radar_hash: str, synthesis_payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        package = self.validate_package(cycle_hash=cycle_hash, radar_hash=radar_hash, synthesis_payload=synthesis_payload)
        synthesis_hash = self._hash(package)
        serialized = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now().astimezone().isoformat()
        with self._database.connect() as connection:
            existing = connection.execute("SELECT * FROM athena_investors_syntheses WHERE cycle_hash = ?", (package["cycleHash"],)).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["synthesis_hash"] != synthesis_hash:
                    raise ValueError("El Research Cycle ya tiene una Investors synthesis distinta; model shopping está prohibido.")
                return record
            connection.execute(
                "INSERT INTO athena_investors_syntheses (cycle_hash, radar_hash, synthesis_hash, package_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (package["cycleHash"], package["radarHash"], synthesis_hash, serialized, created_at),
            )
            row = connection.execute("SELECT * FROM athena_investors_syntheses WHERE synthesis_hash = ?", (synthesis_hash,)).fetchone()
        return self.validate_record(self._row(row))

    def get_by_cycle_hash(self, *, cycle_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha(cycle_hash, "cycle_hash")
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM athena_investors_syntheses WHERE cycle_hash = ?", (normalized,)).fetchone()
        if row is None:
            raise ValueError("El Research Cycle no tiene Investors synthesis persistida.")
        return self.validate_record(self._row(row))

    def validate_package(self, *, cycle_hash: str, radar_hash: str, synthesis_payload: dict[str, Any]) -> dict[str, Any]:
        cycle = self._sha(cycle_hash, "cycle_hash")
        radar = self._sha(radar_hash, "radar_hash")
        if not isinstance(synthesis_payload, dict) or synthesis_payload.get("status") != "validated_external_investors_model_output":
            raise ValueError("Investors synthesis perdió su estado validado.")
        for field in ("modelExecutionVerified", "productionTruthClaimed", "independentCorroborationClaimed", "recommendationInfluence", "automaticScoring", "automaticTrading"):
            if synthesis_payload.get(field) is not False:
                raise ValueError(f"Investors synthesis debe mantener {field}=false.")
        assessments = synthesis_payload.get("assessments")
        count = synthesis_payload.get("assessedCount")
        if not isinstance(assessments, list) or not assessments or isinstance(count, bool) or count != len(assessments):
            raise ValueError("Investors synthesis debe conservar assessments completos y reconciliados.")
        ids: set[str] = set()
        fingerprints: set[str] = set()
        for item in assessments:
            if not isinstance(item, dict):
                raise ValueError("Cada assessment Investors debe ser un objeto.")
            evidence_id = str(item.get("evidenceId") or "").strip()
            if not evidence_id or evidence_id in ids:
                raise ValueError("evidenceId Investors es obligatorio y único.")
            ids.add(evidence_id)
            fingerprints.add(self._sha(item.get("assessmentFingerprint"), "assessmentFingerprint"))
            self._sha(item.get("inputFingerprint"), "inputFingerprint")
            for field in ("evidenceProvider", "primarySource", "sourceRef", "publishedAt", "availableAt", "modelProvider", "modelName", "modelVersion"):
                if not str(item.get(field) or "").strip():
                    raise ValueError(f"assessment.{field} es obligatorio.")
        if len(fingerprints) != len(assessments):
            raise ValueError("assessmentFingerprint no puede repetirse.")
        return {"cycleHash": cycle, "radarHash": radar, "synthesis": synthesis_payload}

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        package = record.get("package") if isinstance(record, dict) else None
        if not isinstance(package, dict):
            raise ValueError("Investors synthesis persistida carece de package válido.")
        validated = self.validate_package(cycle_hash=package.get("cycleHash"), radar_hash=package.get("radarHash"), synthesis_payload=package.get("synthesis"))
        if self._sha(record.get("synthesis_hash"), "synthesis_hash") != self._hash(validated):
            raise ValueError("synthesis_hash de Investors no coincide con el package.")
        if record.get("cycle_hash") != validated["cycleHash"] or record.get("radar_hash") != validated["radarHash"]:
            raise ValueError("Investors synthesis persistida perdió su binding al ciclo/Radar.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar Investors synthesis.")
        try:
            package = json.loads(str(row["package_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("package_json de Investors synthesis no es JSON válido.") from exc
        return {"id": int(row["id"]), "cycle_hash": str(row["cycle_hash"]), "radar_hash": str(row["radar_hash"]), "synthesis_hash": str(row["synthesis_hash"]), "package": package, "created_at": str(row["created_at"])}

    def _hash(self, payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

    def _sha(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text
