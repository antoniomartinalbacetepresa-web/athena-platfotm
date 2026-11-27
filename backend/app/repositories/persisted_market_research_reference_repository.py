"""Owner-bound synthetic research references, without copying market prices."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import validated_market_source_provider
from app.services.market_pit_price_selection_service import _stored_utc


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def observation_hash(row: sqlite3.Row) -> str:
    # Versioned field projection: adding an unrelated database column must not
    # invalidate old references, while all originally selected values stay bound.
    fields = ("id", "instrument_id", "observed_at", "open", "high", "low", "close",
              "adjusted_close", "volume", "market_cap_usd", "source_provider",
              "source_timestamp", "retrieved_at")
    return canonical_hash({field: row[field] for field in fields})


class PersistedMarketResearchReferenceRepository:
    """Append references alongside Journal/Cycle in their shared transaction.

    A source-name fixture classification is not independent provenance attestation.
    This implementation deliberately refuses other kinds until a separate rights
    contract is available. Neither this table nor its references authorize orders.
    """

    def __init__(self, database: AthenaDatabase | None = None):
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS athena_market_research_references (
                owner_id INTEGER NOT NULL CHECK(owner_id > 0),
                reference_hash TEXT NOT NULL,
                reference_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, reference_hash)
            )""")

    def build(self, history: dict[str, Any]) -> dict[str, Any]:
        metadata = history["provenance"]
        if (metadata.get("evidenceKind") != "synthetic_fixture"
                or metadata.get("licenceVerified") is not False
                or metadata.get("historicalPointInTimeEligible") is not False
                or metadata.get("productionCoverageClaimed") is not False
                or metadata.get("orderExecutionAllowed") is not False):
            raise ValueError("Solo se admiten referencias sintéticas sin autoridad operativa.")
        points = history["data"]
        if not isinstance(points, list) or not 1 <= len(points) <= 200:
            raise ValueError("Se requieren entre 1 y 200 observaciones persistidas.")
        reference = {
            "schema": "athena.synthetic-market-reference.v1",
            "instrumentId": metadata["instrumentId"], "symbol": points[0]["symbol"],
            "currency": points[0]["currency"], "sourceProvider": metadata["sourceProvider"],
            "asOf": metadata["asOf"], "observedFrom": metadata["observedFrom"],
            "observedTo": metadata["observedTo"], "limit": metadata["limit"],
            "truncated": metadata["truncated"], "evidenceKind": "synthetic_fixture",
            "classificationBasis": "declared_source_name_not_independent_attestation",
            "metadataOnly": True, "licenceVerified": False,
            "historicalPointInTimeEligible": False, "productionEligible": False,
            "automaticTrading": False, "observations": [],
        }
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            for point in points:
                row = connection.execute("SELECT * FROM market_observations WHERE id = ?",
                                         (point["observationId"],)).fetchone()
                if row is None:
                    raise ValueError("La observación seleccionada ya no existe.")
                selected_fields = {"open": "open", "high": "high", "low": "low", "close": "close",
                                   "adjustedClose": "adjusted_close", "volume": "volume"}
                source_time = _stored_utc(row["source_timestamp"])
                if (point["instrumentId"] != row["instrument_id"]
                        or point["sourceProvider"] != row["source_provider"]
                        or _stored_utc(point["timestamp"]) != _stored_utc(row["observed_at"])
                        or _stored_utc(point["retrievedAt"]) != _stored_utc(row["retrieved_at"])
                        or _stored_utc(point.get("sourceTimestamp")) != source_time
                        or (row["source_timestamp"] is not None and source_time is None)
                        or any(point.get(field) != row[column] for field, column in selected_fields.items())):
                    raise ValueError("La observación cambió desde la selección del histórico.")
                reference["observations"].append({
                    "observationId": point["observationId"],
                    "rowHash": observation_hash(row),
                    "observedAt": point["timestamp"],
                    "retrievedAt": point["retrievedAt"],
                    "availableAt": point["availableAt"],
                })
            self.validate(reference, connection=connection)
        return reference

    def validate(self, reference: dict[str, Any], *, connection: sqlite3.Connection) -> str:
        expected = {"schema", "instrumentId", "symbol", "currency", "sourceProvider", "asOf",
                    "observedFrom", "observedTo", "limit", "truncated", "evidenceKind",
                    "classificationBasis", "metadataOnly", "licenceVerified",
                    "historicalPointInTimeEligible", "productionEligible", "automaticTrading",
                    "observations"}
        if not isinstance(reference, dict) or set(reference) != expected:
            raise ValueError("Contrato de referencia inválido; no se admiten precios adjuntos.")
        if (reference["schema"] != "athena.synthetic-market-reference.v1"
                or reference["evidenceKind"] != "synthetic_fixture"
                or reference["classificationBasis"] != "declared_source_name_not_independent_attestation"
                or reference["metadataOnly"] is not True
                or any(reference[key] is not False for key in
                       ("licenceVerified", "historicalPointInTimeEligible", "productionEligible", "automaticTrading"))):
            raise ValueError("La referencia perdió su límite sintético y de solo investigación.")
        instrument_id = reference["instrumentId"]
        if type(instrument_id) is not int or instrument_id <= 0:
            raise ValueError("Identidad interna inválida.")
        provider = validated_market_source_provider(reference["sourceProvider"])
        # Reuse the same server policy as the history projection, not a flag
        # supplied by an API client. Import lazily to keep repositories acyclic.
        from app.services.persisted_market_history_service import classify_persisted_market_evidence
        if classify_persisted_market_evidence(provider) != "synthetic_fixture":
            raise ValueError("El origen no está identificado como fixture sintético.")
        start, end, cutoff = [_stored_utc(reference[key]) for key in ("observedFrom", "observedTo", "asOf")]
        if (start is None or end is None or cutoff is None or not start <= end <= cutoff
                or cutoff > datetime.now(timezone.utc)
                or (end - start).total_seconds() > 366 * 86400
                or type(reference["limit"]) is not int or not 1 <= reference["limit"] <= 200
                or type(reference["truncated"]) is not bool):
            raise ValueError("Selección temporal inválida.")
        listing = connection.execute("SELECT * FROM instruments WHERE id = ?", (instrument_id,)).fetchone()
        if (listing is None or listing["symbol"] != reference["symbol"]
                or listing["currency"] != reference["currency"]):
            raise ValueError("La identidad del histórico cambió.")
        rows = reference["observations"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= reference["limit"]:
            raise ValueError("Observaciones de referencia inválidas.")
        ids = set()
        previous = None
        for item in rows:
            if (not isinstance(item, dict) or set(item) != {
                "observationId", "rowHash", "observedAt", "retrievedAt", "availableAt"}
                or type(item["observationId"]) is not int or item["observationId"] <= 0
                or item["observationId"] in ids):
                raise ValueError("Identidad de observación inválida o duplicada.")
            ids.add(item["observationId"])
            row = connection.execute("SELECT * FROM market_observations WHERE id = ?",
                                     (item["observationId"],)).fetchone()
            observed, retrieved = _stored_utc(item["observedAt"]), _stored_utc(item["retrievedAt"])
            if (row is None or row["instrument_id"] != instrument_id or row["source_provider"] != provider
                    or observation_hash(row) != item["rowHash"]
                    or observed is None or retrieved is None
                    or observed != _stored_utc(row["observed_at"])
                    or retrieved != _stored_utc(row["retrieved_at"])
                    or _stored_utc(item["availableAt"]) != retrieved
                    or not start <= observed <= end or not observed <= retrieved <= cutoff
                    or (previous is not None and observed <= previous)):
                raise ValueError("La referencia ya no coincide con la evidencia persistida.")
            previous = observed
        return canonical_hash(reference)

    def append(self, reference: dict[str, Any], *, owner_id: int,
               connection: sqlite3.Connection) -> dict[str, Any]:
        self._owner(owner_id)
        digest = self.validate(reference, connection=connection)
        serialized = json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        existing = connection.execute(
            "SELECT reference_json FROM athena_market_research_references WHERE owner_id = ? AND reference_hash = ?",
            (owner_id, digest),
        ).fetchone()
        if existing is not None and existing["reference_json"] != serialized:
            raise ValueError("La referencia existente perdió su integridad.")
        connection.execute("""INSERT OR IGNORE INTO athena_market_research_references
            (owner_id, reference_hash, reference_json, created_at) VALUES (?, ?, ?, ?)""",
            (owner_id, digest, serialized, datetime.now(timezone.utc).isoformat()))
        return {"referenceHash": digest, "sourceRef": f"urn:athena:market-history:{digest}",
                "evidenceKind": "synthetic_fixture", "metadataOnly": True,
                "licenceVerified": False, "historicalPointInTimeEligible": False,
                "productionEligible": False, "automaticTrading": False}

    def get(self, digest: str, *, owner_id: int) -> dict[str, Any]:
        self._owner(owner_id)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise LookupError("Referencia no encontrada.")
        self.initialize()
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute("""SELECT * FROM athena_market_research_references
                WHERE owner_id = ? AND reference_hash = ?""", (owner_id, digest)).fetchone()
            if row is None:
                raise LookupError("Referencia no encontrada.")
            reference = json.loads(row["reference_json"])
            if self.validate(reference, connection=connection) != digest:
                raise ValueError("La referencia persistida perdió su integridad.")
        return {"referenceHash": digest, "reference": reference, "createdAt": row["created_at"]}

    @staticmethod
    def _owner(owner_id: int) -> None:
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Propietario inválido.")
