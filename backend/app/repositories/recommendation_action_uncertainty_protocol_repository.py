from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationActionUncertaintyProtocolRepository:
    """Append-only protocol for uncertainty-aware action promotion.

    No confidence multiplier is selected by code. The protocol must be registered
    before the policy freeze and explicitly states the multiplier and the minimum
    acceptable lower bound versus HOLD for each horizon/state. A negative lower-
    bound criterion is structurally forbidden because HOLD is the comparison baseline.
    """

    PROTOCOL_VERSION = "athena-action-uncertainty-protocol-v1"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_action_uncertainty_protocols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    protocol_id TEXT NOT NULL UNIQUE,
                    registered_at TEXT NOT NULL,
                    protocol_json TEXT NOT NULL,
                    protocol_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                """
            )

    def register(self, *, protocol_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validate_draft(protocol_draft)
        registered_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "registeredAt": registered_at}
        fingerprint = self._fingerprint(unsigned)
        protocol = {**unsigned, "protocolFingerprint": fingerprint}
        serialized = self._serialize(protocol)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_recommendation_action_uncertainty_protocols WHERE protocol_id = ?",
                (core["protocolId"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None or record["protocol"] != protocol:
                    raise ValueError("protocolId ya existe; el protocolo de incertidumbre es inmutable.")
                return record
            connection.execute(
                """
                INSERT INTO athena_recommendation_action_uncertainty_protocols (
                    protocol_id, registered_at, protocol_json, protocol_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (core["protocolId"], registered_at, serialized, fingerprint, created_at),
            )
            row = connection.execute(
                "SELECT * FROM athena_recommendation_action_uncertainty_protocols WHERE protocol_id = ?",
                (core["protocolId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar el protocolo de incertidumbre.")
        return result

    def get(self, *, protocol_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._text(protocol_id, "protocol_id")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_recommendation_action_uncertainty_protocols WHERE protocol_id = ?",
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro debe ser un objeto.")
        protocol = record.get("protocol")
        if not isinstance(protocol, dict):
            raise ValueError("El registro carece de protocol.")
        if protocol.get("protocolId") != self._text(record.get("protocol_id"), "protocol_id"):
            raise ValueError("protocolId fue modificado.")
        registered = self._aware(record.get("registered_at"), "registered_at")
        if self._aware(protocol.get("registeredAt"), "registeredAt") != registered:
            raise ValueError("registeredAt fue modificado.")
        supplied = self._sha256(record.get("protocol_fingerprint"), "protocol_fingerprint")
        if protocol.get("protocolFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide.")
        unsigned = dict(protocol)
        unsigned.pop("protocolFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("El protocolo fue modificado después de persistirse.")
        self._validate_persisted(protocol)
        return record

    def _validate_draft(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("protocol_draft debe ser un objeto.")
        if {"registeredAt", "protocolFingerprint"}.intersection(value):
            raise ValueError("registeredAt/protocolFingerprint los genera el registro.")
        if value.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión de protocolo de incertidumbre no compatible.")
        protocol_id = self._text(value.get("protocolId"), "protocolId")
        horizons = self._horizons(value.get("requiredHorizons"))
        criteria = self._criteria(value.get("criteriaByHorizonAndState"), horizons)
        return {
            "artifactVersion": self.PROTOCOL_VERSION,
            "protocolId": protocol_id,
            "requiredHorizons": horizons,
            "requiredStates": list(self.STATES),
            "criteriaByHorizonAndState": criteria,
            "policy": {
                "confidenceMultiplierSource": "explicit_precommitted_protocol",
                "codeDefaultConfidenceMultiplier": False,
                "negativeLowerBoundVsHoldAllowed": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _validate_persisted(self, value: dict[str, Any]) -> None:
        if value.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión persistida no compatible.")
        horizons = self._horizons(value.get("requiredHorizons"))
        if value.get("requiredStates") != list(self.STATES):
            raise ValueError("requiredStates fue modificado.")
        self._criteria(value.get("criteriaByHorizonAndState"), horizons)
        policy = value.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El protocolo carece de policy.")
        if policy.get("codeDefaultConfidenceMultiplier") is not False:
            raise ValueError("No se permiten multiplicadores de confianza por defecto.")
        if policy.get("negativeLowerBoundVsHoldAllowed") is not False:
            raise ValueError("No se permiten límites inferiores negativos frente a HOLD.")

    def _criteria(self, value: object, horizons: list[int]) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict) or set(value) != {str(x) for x in horizons}:
            raise ValueError("Los criterios deben cubrir exactamente requiredHorizons.")
        result: dict[str, dict[str, Any]] = {}
        for horizon in horizons:
            states = value.get(str(horizon))
            if not isinstance(states, dict) or set(states) != set(self.STATES):
                raise ValueError("Los criterios deben cubrir exactamente todos los estados.")
            normalized: dict[str, Any] = {}
            for state in self.STATES:
                criterion = states.get(state)
                if not isinstance(criterion, dict):
                    raise ValueError("Falta un criterio de incertidumbre.")
                multiplier = self._finite(criterion.get("confidenceMultiplier"), "confidenceMultiplier")
                lower = self._finite(
                    criterion.get("minimumLowerConfidenceBoundIncrementalUtilityVsHold"),
                    "minimumLowerConfidenceBoundIncrementalUtilityVsHold",
                )
                if multiplier <= 0:
                    raise ValueError("confidenceMultiplier debe ser positivo.")
                if lower < 0:
                    raise ValueError("El límite inferior mínimo frente a HOLD no puede ser negativo.")
                normalized[state] = {
                    "confidenceMultiplier": multiplier,
                    "minimumLowerConfidenceBoundIncrementalUtilityVsHold": lower,
                }
            result[str(horizon)] = normalized
        return result

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        result: list[int] = []
        for raw in value:
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            result.append(raw)
        if len(set(result)) != len(result):
            raise ValueError("requiredHorizons contiene duplicados.")
        return result

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            protocol = json.loads(str(row["protocol_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("protocol_json no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "protocol_id": str(row["protocol_id"]),
            "registered_at": str(row["registered_at"]),
            "protocol": protocol,
            "protocol_fingerprint": str(row["protocol_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("El protocolo contiene valores no finitos/no serializables.") from exc

    def _fingerprint(self, value: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(value).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

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

    def _aware(self, value: object, field: str) -> str:
        raw = self._text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
