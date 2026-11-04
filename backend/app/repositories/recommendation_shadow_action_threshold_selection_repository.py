from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationShadowActionThresholdSelectionRepository:
    """Persist the first immutable observation boundary for selected thresholds.

    Validation may select a shadow policy, but future confirmation is independent
    only if the selected policy is committed before subsequent outcomes are used.
    The selection fingerprint is unique, so later calls can recover but never move
    the original ``selected_at`` boundary.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-selection-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_shadow_action_threshold_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    selection_fingerprint TEXT NOT NULL UNIQUE,
                    selected_at TEXT NOT NULL,
                    selection_json TEXT NOT NULL,
                    registration_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_action_threshold_selected_at
                ON athena_recommendation_shadow_action_threshold_selections(selected_at);
                """
            )

    def register(
        self,
        *,
        selection: dict[str, Any],
        selected_at: datetime,
    ) -> dict[str, Any]:
        self.initialize()
        self.validate_selection(selection)
        selected = self._aware_datetime(selected_at, "selected_at")
        selection_fingerprint = self._sha256(
            selection.get("selectionFingerprint"), "selectionFingerprint"
        )
        serialized = self._serialize(selection)
        core = {
            "selectionFingerprint": selection_fingerprint,
            "selectedAt": selected.isoformat(),
            "selectionArtifactFingerprint": hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest(),
        }
        registration_fingerprint = hashlib.sha256(
            self._serialize(core).encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_shadow_action_threshold_selections (
                    selection_fingerprint,
                    selected_at,
                    selection_json,
                    registration_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    selection_fingerprint,
                    selected.isoformat(),
                    serialized,
                    registration_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_action_threshold_selections
                WHERE selection_fingerprint = ?
                """,
                (selection_fingerprint,),
            ).fetchone()

        record = self._row(row)
        if record is None:
            raise RuntimeError("No se pudo recuperar la selección de thresholds registrada.")
        return record

    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(selection_fingerprint, "selection_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_shadow_action_threshold_selections
                WHERE selection_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_selection(self, selection: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(selection, dict):
            raise ValueError("La selección de thresholds debe ser un objeto.")
        if selection.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de selección de thresholds no soportada.")
        if selection.get("status") != (
            "shadow_action_threshold_selection_frozen_for_future_confirmation"
        ):
            raise ValueError("Sólo puede registrarse una selección completa y congelada.")
        if selection.get("allRequestedHorizonsAndStatesSelected") is not True:
            raise ValueError("La selección no cubre todos los horizontes y estados.")
        if selection.get("futureReserveConfirmationEligible") is not True:
            raise ValueError("La selección no está preparada para confirmación futura.")
        if selection.get("advisoryStatus") != "no_advice":
            raise ValueError("La selección debe permanecer en no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if selection.get(field) is not False:
                raise ValueError(f"La selección intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if selection.get(field) is not None:
                raise ValueError(f"La selección no puede publicar {field}.")

        policy = selection.get("policy")
        required_policy = {
            "candidateGenerationPartition": "train_signal_only",
            "candidateSelectionPartition": "validation_only",
            "trainRealizedOutcomesUsedForSelection": False,
            "futureReserveConsumed": False,
            "selectedResearchThresholdsMayBeRefitOnFutureReserve": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }
        if policy != required_policy:
            raise ValueError("La policy de selección fue alterada.")

        core_keys = (
            "artifactVersion",
            "sourceUtilityPanelFingerprint",
            "candidateSetFingerprint",
            "economicContractFingerprint",
            "requestedHorizons",
            "minimumValidationRowsPerState",
            "allRequestedHorizonsAndStatesSelected",
            "selections",
        )
        core = {key: selection.get(key) for key in core_keys}
        expected = self._fingerprint(core)
        actual = self._sha256(
            selection.get("selectionFingerprint"), "selectionFingerprint"
        )
        if expected != actual:
            raise ValueError("La selección de thresholds fue modificada tras su creación.")
        self._sha256(
            selection.get("sourceUtilityPanelFingerprint"),
            "sourceUtilityPanelFingerprint",
        )
        self._sha256(selection.get("candidateSetFingerprint"), "candidateSetFingerprint")
        self._sha256(
            selection.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )
        horizons = selection.get("requestedHorizons")
        if not isinstance(horizons, list) or not horizons:
            raise ValueError("requestedHorizons debe ser una lista no vacía.")
        if len(set(horizons)) != len(horizons):
            raise ValueError("requestedHorizons contiene duplicados.")
        selections = selection.get("selections")
        if not isinstance(selections, dict):
            raise ValueError("La selección carece de payload por horizonte.")
        for horizon in horizons:
            if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
                raise ValueError("requestedHorizons contiene un horizonte inválido.")
            payload = selections.get(str(horizon))
            if not isinstance(payload, dict) or payload.get("horizonDays") != horizon:
                raise ValueError("Falta una selección para un horizonte solicitado.")
            if payload.get("allStatesSelected") is not True:
                raise ValueError("Un horizonte no tiene todos los estados seleccionados.")
            states = payload.get("states")
            if not isinstance(states, dict) or set(states) != {
                "flat",
                "reduced_long",
                "full_long",
            }:
                raise ValueError("Los estados seleccionados no coinciden con el contrato.")
            for state, state_payload in states.items():
                if not isinstance(state_payload, dict):
                    raise ValueError("Una selección de estado es inválida.")
                if state_payload.get("status") != "validation_selected_shadow_policy":
                    raise ValueError("Un estado no contiene una política seleccionada.")
                selected_policy = state_payload.get("selectedPolicy")
                if not isinstance(selected_policy, dict):
                    raise ValueError("Un estado carece de selectedPolicy.")
                if selected_policy.get("currentState") != state:
                    raise ValueError("La política seleccionada pertenece a otro estado.")
                self._sha256(
                    selected_policy.get("policyFingerprint"), "policyFingerprint"
                )
        return selection

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        selection = record.get("selection")
        if not isinstance(selection, dict):
            raise ValueError("El registro no contiene una selección válida.")
        self.validate_selection(selection)
        core = {
            "selectionFingerprint": self._sha256(
                record.get("selection_fingerprint"), "selection_fingerprint"
            ),
            "selectedAt": self._aware_iso(record.get("selected_at"), "selected_at"),
            "selectionArtifactFingerprint": hashlib.sha256(
                self._serialize(selection).encode("utf-8")
            ).hexdigest(),
        }
        if selection.get("selectionFingerprint") != core["selectionFingerprint"]:
            raise ValueError("El registro no corresponde a la selección persistida.")
        expected = hashlib.sha256(self._serialize(core).encode("utf-8")).hexdigest()
        actual = self._sha256(
            record.get("registration_fingerprint"), "registration_fingerprint"
        )
        if expected != actual:
            raise ValueError("El registro de selección fue modificado tras persistirse.")
        return record

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            selection = json.loads(str(row["selection_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("selection_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "selection_fingerprint": str(row["selection_fingerprint"]),
            "selected_at": str(row["selected_at"]),
            "selection": selection,
            "registration_fingerprint": str(row["registration_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _aware_datetime(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _aware_iso(self, value: object, field: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_datetime(parsed, field).isoformat()
