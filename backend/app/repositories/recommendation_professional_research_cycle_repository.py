from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


class RecommendationProfessionalResearchCycleRepository:
    """Append-only persistence for complete professional research-cycle packages.

    A persisted record binds the exact Radar, Investment Journal and Devil's
    Advocate payloads to the cycle SHA-256. The repository never updates or
    deletes a cycle. Re-reading a record recomputes every component hash and the
    aggregate cycle hash, so direct database tampering fails closed.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_professional_research_cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    journal_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    radar_hash TEXT NOT NULL,
                    devils_advocate_hash TEXT NOT NULL,
                    cycle_hash TEXT NOT NULL UNIQUE,
                    package_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (journal_id, revision_id)
                );

                CREATE INDEX IF NOT EXISTS idx_professional_research_cycle_journal
                ON athena_professional_research_cycles(journal_id, id);
                """
            )

    def validate_package(
        self,
        *,
        cycle_payload: dict[str, Any],
        radar_payload: dict[str, Any],
        journal_payload: dict[str, Any],
        devils_advocate_payload: dict[str, Any],
    ) -> dict[str, Any]:
        for name, payload in (
            ("cycle", cycle_payload),
            ("radar", radar_payload),
            ("journal", journal_payload),
            ("devilsAdvocate", devils_advocate_payload),
        ):
            if not isinstance(payload, dict):
                raise ValueError(f"{name} debe ser un objeto persistible.")
            self._assert_research_only(payload, name)
            self._assert_no_forbidden_sources(payload)

        integrity = cycle_payload.get("integrity")
        if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
            raise ValueError("El ciclo perdió su contrato de integridad SHA-256.")

        instrument_id = self._required_text(cycle_payload.get("instrumentId"), "instrumentId")
        symbol = self._required_text(cycle_payload.get("symbol"), "symbol").upper()
        as_of = self._aware_iso(cycle_payload.get("asOf"), "asOf").isoformat()
        journal_id = self._required_text(cycle_payload.get("journal", {}).get("journalId"), "journalId")
        revision_id = self._required_text(cycle_payload.get("journal", {}).get("revisionId"), "revisionId")
        snapshot_hash = self._sha256(cycle_payload.get("journal", {}).get("snapshotHash"), "snapshotHash")

        candidates = radar_payload.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise ValueError("El paquete persistido debe contener exactamente un candidato Radar.")
        candidate = candidates[0]
        if self._required_text(candidate.get("instrumentId"), "radar.instrumentId") != instrument_id:
            raise ValueError("La identidad Radar no coincide con el ciclo persistido.")
        if self._required_text(candidate.get("symbol"), "radar.symbol").upper() != symbol:
            raise ValueError("El símbolo Radar no coincide con el ciclo persistido.")
        if self._aware_iso(radar_payload.get("asOf"), "radar.asOf").isoformat() != as_of:
            raise ValueError("Radar no comparte el asOf exacto del ciclo persistido.")

        if self._required_text(journal_payload.get("journalId"), "journal.journalId") != journal_id:
            raise ValueError("journalId no coincide con el ciclo persistido.")
        if self._required_text(journal_payload.get("revisionId"), "journal.revisionId") != revision_id:
            raise ValueError("revisionId no coincide con el ciclo persistido.")
        if self._required_text(journal_payload.get("symbol"), "journal.symbol").upper() != symbol:
            raise ValueError("El símbolo del Journal no coincide con el ciclo persistido.")
        if self._aware_iso(journal_payload.get("asOf"), "journal.asOf").isoformat() != as_of:
            raise ValueError("Journal no comparte el asOf exacto del ciclo persistido.")
        if self._sha256(journal_payload.get("snapshotHash"), "journal.snapshotHash") != snapshot_hash:
            raise ValueError("El snapshotHash del Journal no coincide con el ciclo persistido.")

        if self._required_text(devils_advocate_payload.get("journalId"), "devilsAdvocate.journalId") != journal_id:
            raise ValueError("Devil's Advocate no coincide con journalId.")
        if self._required_text(devils_advocate_payload.get("revisionId"), "devilsAdvocate.revisionId") != revision_id:
            raise ValueError("Devil's Advocate no coincide con revisionId.")
        if self._required_text(devils_advocate_payload.get("symbol"), "devilsAdvocate.symbol").upper() != symbol:
            raise ValueError("Devil's Advocate no coincide con el símbolo.")
        if self._aware_iso(devils_advocate_payload.get("asOf"), "devilsAdvocate.asOf").isoformat() != as_of:
            raise ValueError("Devil's Advocate no comparte el asOf exacto del ciclo persistido.")
        if self._sha256(devils_advocate_payload.get("snapshotHash"), "devilsAdvocate.snapshotHash") != snapshot_hash:
            raise ValueError("Devil's Advocate no coincide con el snapshotHash del Journal.")

        radar_hash = self._canonical_hash(radar_payload)
        devils_hash = self._canonical_hash(devils_advocate_payload)
        if self._sha256(integrity.get("radarHash"), "integrity.radarHash") != radar_hash:
            raise ValueError("El payload Radar no coincide con radarHash.")
        if self._sha256(integrity.get("journalSnapshotHash"), "integrity.journalSnapshotHash") != snapshot_hash:
            raise ValueError("journalSnapshotHash no coincide con el snapshot persistido.")
        if self._sha256(integrity.get("devilsAdvocateHash"), "integrity.devilsAdvocateHash") != devils_hash:
            raise ValueError("El payload Devil's Advocate no coincide con devilsAdvocateHash.")

        expected_cycle_hash = self._canonical_hash(
            {
                "instrumentId": instrument_id,
                "symbol": symbol,
                "asOf": as_of,
                "journalId": journal_id,
                "revisionId": revision_id,
                "radarHash": radar_hash,
                "journalSnapshotHash": snapshot_hash,
                "devilsAdvocateHash": devils_hash,
            }
        )
        cycle_hash = self._sha256(integrity.get("cycleHash"), "integrity.cycleHash")
        if cycle_hash != expected_cycle_hash:
            raise ValueError("El paquete completo no coincide con cycleHash.")

        return {
            "cycle": cycle_payload,
            "radar": radar_payload,
            "journal": journal_payload,
            "devilsAdvocate": devils_advocate_payload,
        }

    def append(
        self,
        *,
        cycle_payload: dict[str, Any],
        radar_payload: dict[str, Any],
        journal_payload: dict[str, Any],
        devils_advocate_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        package = self.validate_package(
            cycle_payload=cycle_payload,
            radar_payload=radar_payload,
            journal_payload=journal_payload,
            devils_advocate_payload=devils_advocate_payload,
        )
        cycle = package["cycle"]
        integrity = cycle["integrity"]
        journal = cycle["journal"]
        instrument_id = str(cycle["instrumentId"])
        symbol = str(cycle["symbol"]).upper()
        as_of = str(cycle["asOf"])
        journal_id = str(journal["journalId"])
        revision_id = str(journal["revisionId"])
        snapshot_hash = str(journal["snapshotHash"])
        radar_hash = str(integrity["radarHash"])
        devils_hash = str(integrity["devilsAdvocateHash"])
        cycle_hash = str(integrity["cycleHash"])
        serialized = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing_revision = connection.execute(
                "SELECT * FROM athena_professional_research_cycles WHERE journal_id = ? AND revision_id = ?",
                (journal_id, revision_id),
            ).fetchone()
            if existing_revision is not None:
                record = self._row(existing_revision)
                if record["cycle_hash"] != cycle_hash:
                    raise ValueError("La revisión ya tiene un Research Cycle distinto; el historial es inmutable.")
                return self.validate_record(record)

            duplicate = connection.execute(
                "SELECT * FROM athena_professional_research_cycles WHERE cycle_hash = ?",
                (cycle_hash,),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("cycleHash ya está persistido con otra identidad.")

            connection.execute(
                """
                INSERT INTO athena_professional_research_cycles (
                    instrument_id, symbol, as_of, journal_id, revision_id,
                    snapshot_hash, radar_hash, devils_advocate_hash, cycle_hash,
                    package_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id, symbol, as_of, journal_id, revision_id,
                    snapshot_hash, radar_hash, devils_hash, cycle_hash,
                    serialized, created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_professional_research_cycles WHERE cycle_hash = ?",
                (cycle_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, cycle_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(cycle_hash, "cycle_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_professional_research_cycles WHERE cycle_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe un Professional Research Cycle con ese cycleHash.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro persistido del ciclo debe ser un objeto.")
        package = record.get("package")
        if not isinstance(package, dict):
            raise ValueError("El Research Cycle persistido carece de package válido.")
        validated = self.validate_package(
            cycle_payload=package.get("cycle"),
            radar_payload=package.get("radar"),
            journal_payload=package.get("journal"),
            devils_advocate_payload=package.get("devilsAdvocate"),
        )
        cycle = validated["cycle"]
        integrity = cycle["integrity"]
        journal = cycle["journal"]
        expected = {
            "instrument_id": cycle["instrumentId"],
            "symbol": cycle["symbol"],
            "as_of": cycle["asOf"],
            "journal_id": journal["journalId"],
            "revision_id": journal["revisionId"],
            "snapshot_hash": journal["snapshotHash"],
            "radar_hash": integrity["radarHash"],
            "devils_advocate_hash": integrity["devilsAdvocateHash"],
            "cycle_hash": integrity["cycleHash"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"El campo persistido {field} no coincide con el package canónico.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar el Research Cycle persistido.")
        try:
            package = json.loads(str(row["package_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("package_json persistido no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "instrument_id": str(row["instrument_id"]),
            "symbol": str(row["symbol"]),
            "as_of": str(row["as_of"]),
            "journal_id": str(row["journal_id"]),
            "revision_id": str(row["revision_id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "radar_hash": str(row["radar_hash"]),
            "devils_advocate_hash": str(row["devils_advocate_hash"]),
            "cycle_hash": str(row["cycle_hash"]),
            "package": package,
            "created_at": str(row["created_at"]),
        }

    def _assert_research_only(self, payload: dict[str, Any], module: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{module} perdió advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{module} intentó habilitar producción.")
        if payload.get("isWeightingReady") is not False:
            raise ValueError(f"{module} intentó habilitar ponderación.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError(f"{module} perdió su política de seguridad.")
        if policy.get("automaticTrading") is not False:
            raise ValueError(f"{module} intentó habilitar trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError(f"{module} intentó promover producción automáticamente.")

    def _assert_no_forbidden_sources(self, payload: object) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"source", "sourceRef"} and isinstance(value, str):
                    normalized = value.casefold().replace("_", " ").replace("-", " ")
                    compact = normalized.replace(" ", "")
                    if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
                        raise ValueError("FMP/Financial Modeling Prep está prohibido en ciclos persistidos.")
                self._assert_no_forbidden_sources(value)
        elif isinstance(payload, list):
            for value in payload:
                self._assert_no_forbidden_sources(value)

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal válido.")
        return text

    def _aware_iso(self, value: object, field: str) -> datetime:
        text = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser un datetime ISO válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed
