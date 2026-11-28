from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationActionPromotionProtocolRepository:
    """Append-only registry for precommitted action-policy promotion criteria.

    The repository owns registeredAt and the fingerprint. Callers cannot backdate
    a protocol after seeing future-reserve performance. The registry contains no
    default investment thresholds or sample sizes: every economic/statistical
    criterion must be supplied explicitly before the frozen action policy is selected.
    """

    PROTOCOL_VERSION = "athena-action-promotion-protocol-v2"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_action_promotion_protocols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    protocol_id TEXT NOT NULL UNIQUE,
                    registered_at TEXT NOT NULL,
                    protocol_json TEXT NOT NULL,
                    protocol_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_action_promotion_protocol_registered
                ON athena_recommendation_action_promotion_protocols(registered_at);
                """
            )

    def register(self, *, protocol_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validated_draft(protocol_draft)
        registered_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "registeredAt": registered_at}
        protocol_fingerprint = self._fingerprint(unsigned)
        protocol = {**unsigned, "protocolFingerprint": protocol_fingerprint}
        serialized = self._serialize(protocol)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_protocols
                WHERE protocol_id = ?
                """,
                (core["protocolId"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar el protocolo existente.")
                if record["protocol"] != protocol:
                    raise ValueError(
                        "protocolId ya está registrado; los protocolos de acción son inmutables."
                    )
                return record

            connection.execute(
                """
                INSERT INTO athena_recommendation_action_promotion_protocols (
                    protocol_id, registered_at, protocol_json,
                    protocol_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    core["protocolId"],
                    registered_at,
                    serialized,
                    protocol_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_protocols
                WHERE protocol_id = ?
                """,
                (core["protocolId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar el protocolo registrado.")
        return result

    def get(self, *, protocol_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._non_empty(protocol_id, "protocol_id")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_action_promotion_protocols
                WHERE protocol_id = ?
                """,
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de protocolo debe ser un objeto.")
        protocol_id = self._non_empty(record.get("protocol_id"), "protocol_id")
        registered_at = self._aware_iso(record.get("registered_at"), "registered_at")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        if created_at < registered_at:
            raise ValueError("created_at no puede preceder a registered_at.")
        protocol = record.get("protocol")
        if not isinstance(protocol, dict):
            raise ValueError("El registro carece de protocol válido.")
        if protocol.get("protocolId") != protocol_id:
            raise ValueError("El protocolo persistido cambió de protocolId.")
        if self._aware_iso(protocol.get("registeredAt"), "registeredAt") != registered_at:
            raise ValueError("El protocolo persistido cambió registeredAt.")
        supplied = self._sha256(record.get("protocol_fingerprint"), "protocol_fingerprint")
        if protocol.get("protocolFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide con el protocolo.")
        unsigned = dict(protocol)
        unsigned.pop("protocolFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("El protocolo fue modificado después de persistirse.")
        self._validated_persisted_protocol(protocol)
        return record

    def _validated_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("protocol_draft debe ser un objeto.")
        if {"registeredAt", "protocolFingerprint"}.intersection(payload):
            raise ValueError(
                "registeredAt y protocolFingerprint los genera el registro."
            )
        if payload.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión de protocolo de acciones no compatible.")
        protocol_id = self._non_empty(payload.get("protocolId"), "protocolId")
        horizons = self._horizons(payload.get("requiredHorizons"))
        minimum_rows = self._minimum_rows(
            payload.get("minimumFutureRowsByHorizon"), horizons
        )
        criteria = self._criteria(payload.get("criteriaByHorizonAndState"), horizons)
        return {
            "artifactVersion": self.PROTOCOL_VERSION,
            "protocolId": protocol_id,
            "requiredHorizons": horizons,
            "requiredStates": list(self.STATES),
            "minimumFutureRowsByHorizon": minimum_rows,
            "criteriaByHorizonAndState": criteria,
            "criteriaSemantics": {
                "thresholdsAreCallerPrecommitted": True,
                "minimumFutureRowsAreCallerPrecommitted": True,
                "codeDefaultPromotionThresholds": False,
                "codeDefaultProductionSampleSize": False,
                "comparisonTarget": "frozen_policy_vs_hold_on_first_sealed_future_reserve",
            },
        }

    def _validated_persisted_protocol(self, protocol: dict[str, Any]) -> None:
        if protocol.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión persistida de protocolo no compatible.")
        self._non_empty(protocol.get("protocolId"), "protocolId")
        horizons = self._horizons(protocol.get("requiredHorizons"))
        if protocol.get("requiredStates") != list(self.STATES):
            raise ValueError("requiredStates fue modificado.")
        self._minimum_rows(protocol.get("minimumFutureRowsByHorizon"), horizons)
        self._criteria(protocol.get("criteriaByHorizonAndState"), horizons)
        semantics = protocol.get("criteriaSemantics")
        if not isinstance(semantics, dict):
            raise ValueError("criteriaSemantics es obligatorio.")
        if semantics.get("thresholdsAreCallerPrecommitted") is not True:
            raise ValueError("El protocolo no declara criterios precomprometidos.")
        if semantics.get("minimumFutureRowsAreCallerPrecommitted") is not True:
            raise ValueError("El protocolo no precompromete suficiencia muestral.")
        if semantics.get("codeDefaultPromotionThresholds") is not False:
            raise ValueError("El protocolo no puede depender de thresholds por defecto del código.")
        if semantics.get("codeDefaultProductionSampleSize") is not False:
            raise ValueError("El protocolo no puede depender de tamaño muestral por defecto del código.")

    def _minimum_rows(self, payload: object, horizons: list[int]) -> dict[str, int]:
        if not isinstance(payload, dict):
            raise ValueError("minimumFutureRowsByHorizon es obligatorio.")
        expected = {str(value) for value in horizons}
        if set(payload) != expected:
            raise ValueError(
                "minimumFutureRowsByHorizon debe cubrir exactamente requiredHorizons."
            )
        result: dict[str, int] = {}
        for horizon in horizons:
            key = str(horizon)
            value = payload.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"minimumFutureRowsByHorizon.{key} debe ser entero positivo."
                )
            result[key] = value
        return result

    def _criteria(self, payload: object, horizons: list[int]) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("criteriaByHorizonAndState es obligatorio.")
        expected_horizons = {str(value) for value in horizons}
        if set(payload) != expected_horizons:
            raise ValueError("Los criterios deben cubrir exactamente requiredHorizons.")
        result: dict[str, dict[str, Any]] = {}
        for horizon in horizons:
            key = str(horizon)
            states = payload.get(key)
            if not isinstance(states, dict) or set(states) != set(self.STATES):
                raise ValueError(f"Los criterios de {horizon} días deben cubrir todos los estados.")
            normalized_states: dict[str, Any] = {}
            for state in self.STATES:
                item = states.get(state)
                if not isinstance(item, dict):
                    raise ValueError(f"Faltan criterios para {horizon}/{state}.")
                minimum_incremental = self._finite(
                    item.get("minimumMeanIncrementalUtilityVsHold"),
                    "minimumMeanIncrementalUtilityVsHold",
                )
                maximum_regret = self._finite(
                    item.get("maximumMeanHindsightRegret"),
                    "maximumMeanHindsightRegret",
                )
                if maximum_regret < 0.0:
                    raise ValueError("maximumMeanHindsightRegret no puede ser negativo.")
                normalized_states[state] = {
                    "minimumMeanIncrementalUtilityVsHold": minimum_incremental,
                    "maximumMeanHindsightRegret": maximum_regret,
                }
            result[key] = normalized_states
        return result

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        result: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            result.append(item)
        if len(set(result)) != len(result):
            raise ValueError("requiredHorizons no puede contener duplicados.")
        return result

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            protocol = json.loads(str(row["protocol_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("protocol_json persistido no es válido.") from exc
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
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El protocolo contiene valores no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _non_empty(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._non_empty(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
