from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationProductionAuthorizationRepository:
    """Append-only registry for explicitly authorized production recommendations.

    This repository is intentionally not exposed by a network write endpoint.
    Authorization timestamps and fingerprints are generated server-side so an
    offline governance caller cannot backdate or mutate an authorization.
    """

    ARTIFACT_VERSION = "athena-production-recommendation-authorization-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_production_authorizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    authorization_id TEXT NOT NULL UNIQUE,
                    production_promotion_decision_fingerprint TEXT NOT NULL,
                    calibrated_candidate_fingerprint TEXT NOT NULL,
                    validated_action_candidate_fingerprint TEXT NOT NULL,
                    uncertainty_bound_action_candidate_fingerprint TEXT NOT NULL UNIQUE,
                    operator_id TEXT NOT NULL,
                    authorized_at TEXT NOT NULL,
                    authorization_json TEXT NOT NULL,
                    authorization_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_production_authorization_candidate
                ON athena_recommendation_production_authorizations(
                    calibrated_candidate_fingerprint, authorized_at
                );
                """
            )

    def register(self, *, authorization_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validated_draft(authorization_draft)
        authorized_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "authorizedAt": authorized_at}
        authorization_fingerprint = self._fingerprint(unsigned)
        authorization = {
            **unsigned,
            "authorizationFingerprint": authorization_fingerprint,
        }
        serialized = self._serialize(authorization)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_authorizations
                WHERE authorization_id = ?
                """,
                (core["authorizationId"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la autorización existente.")
                if record["authorization"] != authorization:
                    raise ValueError(
                        "authorizationId ya está registrado; las autorizaciones son inmutables."
                    )
                return record

            duplicate = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_authorizations
                WHERE uncertainty_bound_action_candidate_fingerprint = ?
                """,
                (core["uncertaintyBoundActionCandidateFingerprint"],),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(
                    "El candidato de acción con incertidumbre ya fue autorizado."
                )

            connection.execute(
                """
                INSERT INTO athena_recommendation_production_authorizations (
                    authorization_id,
                    production_promotion_decision_fingerprint,
                    calibrated_candidate_fingerprint,
                    validated_action_candidate_fingerprint,
                    uncertainty_bound_action_candidate_fingerprint,
                    operator_id, authorized_at, authorization_json,
                    authorization_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    core["authorizationId"],
                    core["productionPromotionDecisionFingerprint"],
                    core["calibratedCandidateFingerprint"],
                    core["validatedActionCandidateFingerprint"],
                    core["uncertaintyBoundActionCandidateFingerprint"],
                    core["operatorId"],
                    authorized_at,
                    serialized,
                    authorization_fingerprint,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_authorizations
                WHERE authorization_id = ?
                """,
                (core["authorizationId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la autorización registrada.")
        return result

    def get(self, *, authorization_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._non_empty(authorization_id, "authorization_id")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_authorizations
                WHERE authorization_id = ?
                """,
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de autorización debe ser un objeto.")
        authorization = record.get("authorization")
        if not isinstance(authorization, dict):
            raise ValueError("El registro carece de authorization válida.")
        if authorization.get("authorizationId") != self._non_empty(
            record.get("authorization_id"), "authorization_id"
        ):
            raise ValueError("La autorización persistida cambió authorizationId.")
        for api_key, db_key in (
            (
                "productionPromotionDecisionFingerprint",
                "production_promotion_decision_fingerprint",
            ),
            ("calibratedCandidateFingerprint", "calibrated_candidate_fingerprint"),
            (
                "validatedActionCandidateFingerprint",
                "validated_action_candidate_fingerprint",
            ),
            (
                "uncertaintyBoundActionCandidateFingerprint",
                "uncertainty_bound_action_candidate_fingerprint",
            ),
        ):
            if authorization.get(api_key) != self._sha256(record.get(db_key), db_key):
                raise ValueError(f"La autorización persistida cambió {api_key}.")
        if authorization.get("operatorId") != self._non_empty(
            record.get("operator_id"), "operator_id"
        ):
            raise ValueError("La autorización persistida cambió operatorId.")
        authorized_at = self._aware_iso(record.get("authorized_at"), "authorized_at")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        if created_at < authorized_at:
            raise ValueError("created_at no puede preceder a authorized_at.")
        if self._aware_iso(authorization.get("authorizedAt"), "authorizedAt") != authorized_at:
            raise ValueError("La autorización persistida cambió authorizedAt.")
        supplied = self._sha256(
            record.get("authorization_fingerprint"), "authorization_fingerprint"
        )
        if authorization.get("authorizationFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide con la autorización.")
        unsigned = dict(authorization)
        unsigned.pop("authorizationFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("La autorización fue modificada después de persistirse.")
        self._validated_draft(
            {
                key: value
                for key, value in authorization.items()
                if key not in {"authorizedAt", "authorizationFingerprint"}
            }
        )
        return record

    def _validated_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("authorization_draft debe ser un objeto.")
        if {"authorizedAt", "authorizationFingerprint"}.intersection(payload):
            raise ValueError(
                "authorizedAt y authorizationFingerprint los genera el registro."
            )
        if payload.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de autorización productiva no compatible.")
        if payload.get("status") != "production_recommendation_authorized":
            raise ValueError("La autorización debe declarar el estado productivo exacto.")
        if payload.get("humanReviewConfirmed") is not True:
            raise ValueError("La autorización requiere revisión humana explícita.")
        if payload.get("authorizationMethod") != "offline_local_operator":
            raise ValueError("Sólo se admite autorización offline local.")
        if payload.get("advisoryStatus") != "production_recommendation":
            raise ValueError("advisoryStatus productivo inválido.")
        if payload.get("recommendationCandidateReady") is not True:
            raise ValueError("La recomendación autorizada debe estar preparada.")
        if payload.get("productionEligible") is not True:
            raise ValueError("La autorización productiva debe ser explícita.")
        if payload.get("allocationEligible") is not False:
            raise ValueError("La autorización de recomendación no autoriza allocation.")
        if payload.get("automaticProductionPromotion") is not False:
            raise ValueError("La promoción automática debe permanecer deshabilitada.")
        if payload.get("automaticTrading") is not False:
            raise ValueError("El trading automático debe permanecer deshabilitado.")
        action = self._non_empty(payload.get("action"), "action").lower()
        if action not in {"buy", "hold", "reduce", "sell"}:
            raise ValueError("Acción productiva no soportada.")
        horizon = payload.get("horizonDays")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ValueError("horizonDays debe ser entero positivo.")
        reason = self._non_empty(payload.get("authorizationReason"), "authorizationReason")
        if len(reason) < 20:
            raise ValueError("authorizationReason debe documentar la decisión de gobierno.")
        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "authorizationId": self._non_empty(
                payload.get("authorizationId"), "authorizationId"
            ),
            "status": "production_recommendation_authorized",
            "productionPromotionDecisionId": self._non_empty(
                payload.get("productionPromotionDecisionId"),
                "productionPromotionDecisionId",
            ),
            "productionPromotionDecisionFingerprint": self._sha256(
                payload.get("productionPromotionDecisionFingerprint"),
                "productionPromotionDecisionFingerprint",
            ),
            "calibratedCandidateFingerprint": self._sha256(
                payload.get("calibratedCandidateFingerprint"),
                "calibratedCandidateFingerprint",
            ),
            "validatedActionCandidateFingerprint": self._sha256(
                payload.get("validatedActionCandidateFingerprint"),
                "validatedActionCandidateFingerprint",
            ),
            "uncertaintyBoundActionCandidateFingerprint": self._sha256(
                payload.get("uncertaintyBoundActionCandidateFingerprint"),
                "uncertaintyBoundActionCandidateFingerprint",
            ),
            "actionPromotionDecisionId": self._non_empty(
                payload.get("actionPromotionDecisionId"), "actionPromotionDecisionId"
            ),
            "actionPromotionDecisionFingerprint": self._sha256(
                payload.get("actionPromotionDecisionFingerprint"),
                "actionPromotionDecisionFingerprint",
            ),
            "candidateFingerprint": self._sha256(
                payload.get("candidateFingerprint"), "candidateFingerprint"
            ),
            "instrumentId": self._non_empty(payload.get("instrumentId"), "instrumentId"),
            "symbol": self._non_empty(payload.get("symbol"), "symbol"),
            "asOf": self._aware_iso(payload.get("asOf"), "asOf"),
            "horizonDays": horizon,
            "modelFingerprint": self._sha256(
                payload.get("modelFingerprint"), "modelFingerprint"
            ),
            "policyState": self._non_empty(payload.get("policyState"), "policyState"),
            "policyFingerprint": self._sha256(
                payload.get("policyFingerprint"), "policyFingerprint"
            ),
            "action": action,
            "operatorId": self._non_empty(payload.get("operatorId"), "operatorId"),
            "authorizationReason": reason,
            "humanReviewConfirmed": True,
            "authorizationMethod": "offline_local_operator",
            "advisoryStatus": "production_recommendation",
            "recommendationCandidateReady": True,
            "productionEligible": True,
            "allocationEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "networkWriteEndpointExposed": False,
                "humanAuthorizationRequired": True,
                "authorizationDoesNotAuthorizeAllocation": True,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            authorization = json.loads(str(row["authorization_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("authorization_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "authorization_id": str(row["authorization_id"]),
            "production_promotion_decision_fingerprint": str(
                row["production_promotion_decision_fingerprint"]
            ),
            "calibrated_candidate_fingerprint": str(
                row["calibrated_candidate_fingerprint"]
            ),
            "validated_action_candidate_fingerprint": str(
                row["validated_action_candidate_fingerprint"]
            ),
            "uncertainty_bound_action_candidate_fingerprint": str(
                row["uncertainty_bound_action_candidate_fingerprint"]
            ),
            "operator_id": str(row["operator_id"]),
            "authorized_at": str(row["authorized_at"]),
            "authorization": authorization,
            "authorization_fingerprint": str(row["authorization_fingerprint"]),
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
            raise ValueError(
                "La autorización contiene valores no serializables o no finitos."
            ) from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _non_empty(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._non_empty(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
