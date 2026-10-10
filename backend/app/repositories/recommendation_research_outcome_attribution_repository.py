from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class RecommendationResearchOutcomeAttributionRepository:
    """Append-only tamper-evident storage for posterior outcome attributions."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_outcome_attributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_hash TEXT NOT NULL,
                    outcome_id TEXT NOT NULL,
                    outcome_hash TEXT NOT NULL UNIQUE,
                    instrument_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    cycle_as_of TEXT NOT NULL,
                    outcome_as_of TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (cycle_hash, outcome_id)
                );

                CREATE INDEX IF NOT EXISTS idx_research_outcome_cycle
                ON athena_research_outcome_attributions(cycle_hash, id);
                """
            )

    def append(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        normalized = self.validate_payload(payload)
        serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now().astimezone().isoformat()
        cycle_hash = str(normalized["cycleHash"])
        outcome_id = str(normalized["outcomeId"])
        outcome_hash = str(normalized["outcomeHash"])

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_research_outcome_attributions WHERE cycle_hash = ? AND outcome_id = ?",
                (cycle_hash, outcome_id),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["outcome_hash"] != outcome_hash:
                    raise ValueError("outcomeId ya existe para este cycleHash con contenido distinto.")
                return self.validate_record(record)

            duplicate = connection.execute(
                "SELECT * FROM athena_research_outcome_attributions WHERE outcome_hash = ?",
                (outcome_hash,),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("outcomeHash ya existe con otra identidad.")

            connection.execute(
                """
                INSERT INTO athena_research_outcome_attributions (
                    cycle_hash, outcome_id, outcome_hash, instrument_id, symbol,
                    cycle_as_of, outcome_as_of, period_start, period_end,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_hash,
                    outcome_id,
                    outcome_hash,
                    normalized["instrumentId"],
                    normalized["symbol"],
                    normalized["cycleAsOf"],
                    normalized["asOf"],
                    normalized["periodStart"],
                    normalized["periodEnd"],
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_outcome_attributions WHERE outcome_hash = ?",
                (outcome_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, outcome_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(outcome_hash, "outcome_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_outcome_attributions WHERE outcome_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe un outcome attribution con ese hash.")
        return self.validate_record(self._row(row))

    def validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Outcome attribution debe ser un objeto.")
        if payload.get("module") != "research_outcome_attribution":
            raise ValueError("Outcome attribution perdió module.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("Outcome attribution perdió no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("Outcome attribution intentó producción.")
        if payload.get("isWeightingReady") is not False:
            raise ValueError("Outcome attribution intentó weighting.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Outcome attribution perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("Outcome attribution intentó trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Outcome attribution intentó promoción automática.")
        if policy.get("learning") != "research_only_not_automatic_model_update":
            raise ValueError("Outcome attribution intentó aprendizaje automático no validado.")
        if policy.get("causalClaim") != "forbidden_arithmetic_attribution_only":
            raise ValueError("Outcome attribution intentó inferencia causal.")
        if policy.get("fx") != "explicit_currency_pair_bound_fail_closed":
            raise ValueError("Outcome attribution perdió seguridad FX.")
        if policy.get("identity") != "outcome_hash_binds_cycle_hash_and_exact_attribution_payload":
            raise ValueError("Outcome attribution perdió identidad canónica.")

        attribution = payload.get("attribution")
        if not isinstance(attribution, dict):
            raise ValueError("Outcome attribution perdió Performance Attribution anidado.")
        attribution_key = self._sha256(payload.get("attributionKey"), "attributionKey")
        if self._sha256(attribution.get("attributionKey"), "attribution.attributionKey") != attribution_key:
            raise ValueError("attributionKey no coincide con Performance Attribution anidado.")
        benchmark_id = self._text(payload.get("benchmarkId"), "benchmarkId")
        if self._text(attribution.get("benchmarkId"), "attribution.benchmarkId") != benchmark_id:
            raise ValueError("benchmarkId no coincide con Performance Attribution anidado.")

        currency = self._currency_contract(payload.get("currency"), "currency")
        attribution_currency = self._currency_contract(attribution.get("currency"), "attribution.currency")
        if currency != attribution_currency:
            raise ValueError("El contrato de moneda no coincide con Performance Attribution anidado.")

        cycle_hash = self._sha256(payload.get("cycleHash"), "cycleHash")
        outcome_hash = self._sha256(payload.get("outcomeHash"), "outcomeHash")
        canonical = {
            "outcomeId": self._text(payload.get("outcomeId"), "outcomeId"),
            "cycleHash": cycle_hash,
            "instrumentId": self._text(payload.get("instrumentId"), "instrumentId"),
            "symbol": self._text(payload.get("symbol"), "symbol").upper(),
            "cycleAsOf": self._text(payload.get("cycleAsOf"), "cycleAsOf"),
            "attribution": attribution,
        }
        expected = self._canonical_hash(canonical)
        if outcome_hash != expected:
            raise ValueError("Outcome attribution no coincide con outcomeHash canónico.")
        return payload

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Registro de outcome carece de payload válido.")
        validated = self.validate_payload(payload)
        expected = {
            "cycle_hash": validated["cycleHash"],
            "outcome_id": validated["outcomeId"],
            "outcome_hash": validated["outcomeHash"],
            "instrument_id": validated["instrumentId"],
            "symbol": validated["symbol"],
            "cycle_as_of": validated["cycleAsOf"],
            "outcome_as_of": validated["asOf"],
            "period_start": validated["periodStart"],
            "period_end": validated["periodEnd"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con payload canónico.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar outcome attribution persistido.")
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("payload_json de outcome no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "cycle_hash": str(row["cycle_hash"]),
            "outcome_id": str(row["outcome_id"]),
            "outcome_hash": str(row["outcome_hash"]),
            "instrument_id": str(row["instrument_id"]),
            "symbol": str(row["symbol"]),
            "cycle_as_of": str(row["cycle_as_of"]),
            "outcome_as_of": str(row["outcome_as_of"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "payload": payload,
            "created_at": str(row["created_at"]),
        }

    def _currency_contract(self, value: object, field: str) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError(f"{field} debe ser un objeto de moneda válido.")
        instrument = self._currency(value.get("instrumentCurrency"), f"{field}.instrumentCurrency")
        reporting = self._currency(value.get("reportingCurrency"), f"{field}.reportingCurrency")
        fx_pair = self._text(value.get("fxPair"), f"{field}.fxPair").upper()
        if fx_pair != f"{instrument}/{reporting}":
            raise ValueError(f"{field}.fxPair es inconsistente.")
        conversion_required = instrument != reporting
        if value.get("conversionRequired") is not conversion_required:
            raise ValueError(f"{field}.conversionRequired es inconsistente.")
        return {
            "instrumentCurrency": instrument,
            "reportingCurrency": reporting,
            "fxPair": fx_pair,
            "conversionRequired": conversion_required,
        }

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _currency(self, value: object, field: str) -> str:
        text = self._text(value, field).upper()
        if _CURRENCY_RE.fullmatch(text) is None:
            raise ValueError(f"{field} debe ser código de moneda de tres letras.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text
