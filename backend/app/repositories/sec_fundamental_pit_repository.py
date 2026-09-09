from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.sec_fundamental_pit_service import FundamentalPitFact


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SecFundamentalPitRepository:
    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sec_fundamental_pit_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_key TEXT NOT NULL UNIQUE,
                    cik TEXT NOT NULL,
                    taxonomy TEXT NOT NULL,
                    concept TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    accession_number TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(cik, taxonomy, concept, unit, accession_number, artifact_json)
                );
                CREATE INDEX IF NOT EXISTS idx_sec_fundamental_pit_lookup
                ON sec_fundamental_pit_facts(cik, concept, available_at, id);
                """
            )

    def append(self, fact: FundamentalPitFact) -> dict[str, Any]:
        self.initialize()
        artifact = fact.to_api_dict()
        key = str(artifact["factKey"])
        if _SHA256_RE.fullmatch(key) is None:
            raise ValueError("factKey inválido.")
        serialized = json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM sec_fundamental_pit_facts WHERE fact_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact"] != artifact:
                    raise ValueError("factKey ya existe con otro contenido.")
                return record
            connection.execute(
                """
                INSERT INTO sec_fundamental_pit_facts
                (fact_key, cik, taxonomy, concept, unit, accession_number, available_at, artifact_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    fact.cik,
                    fact.taxonomy,
                    fact.concept,
                    fact.unit,
                    fact.accession_number,
                    fact.available_at.isoformat(),
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sec_fundamental_pit_facts WHERE fact_key = ?", (key,)
            ).fetchone()
        return self._row(row)

    def get_known_at_or_before(self, *, cik: str, as_of: datetime, concept: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        normalized_cik = "".join(ch for ch in str(cik) if ch.isdigit()).zfill(10)
        with self._database.connect() as connection:
            if concept is None:
                rows = connection.execute(
                    "SELECT * FROM sec_fundamental_pit_facts WHERE cik = ? AND available_at <= ? ORDER BY available_at, id",
                    (normalized_cik, cutoff),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM sec_fundamental_pit_facts WHERE cik = ? AND concept = ? AND available_at <= ? ORDER BY available_at, id",
                    (normalized_cik, concept, cutoff),
                ).fetchall()
        return [self._validate_record(self._row(row)) for row in rows]

    def _validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record["artifact"]
        if artifact.get("factKey") != record["fact_key"]:
            raise ValueError("Registro fundamental manipulado: factKey no coincide.")
        if artifact.get("cik") != record["cik"]:
            raise ValueError("Registro fundamental manipulado: CIK no coincide.")
        provenance = artifact.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("source") != "sec_edgar":
            raise ValueError("Registro fundamental carece de provenance SEC válida.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Registro fundamental violó límites de producción/weighting.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar fact fundamental.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json fundamental inválido.") from exc
        return {
            "id": int(row["id"]),
            "fact_key": str(row["fact_key"]),
            "cik": str(row["cik"]),
            "taxonomy": str(row["taxonomy"]),
            "concept": str(row["concept"]),
            "unit": str(row["unit"]),
            "accession_number": str(row["accession_number"]),
            "available_at": str(row["available_at"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }
