from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_allocation_authorization_repository import (
    RecommendationProductionAllocationAuthorizationRepository,
)
from app.repositories.recommendation_production_authorization_repository import (
    RecommendationProductionAuthorizationRepository,
)


class RecommendationProductionReadService:
    """Read-only PIT view over persisted production authorizations.

    This service never promotes or writes an authorization. It only exposes artifacts
    that were already persisted and known by the requested cutoff, after re-running
    the repositories' integrity validation. Allocation is returned only when it binds
    to the recommendation authorization selected for the same instrument/context.
    Optional symbol/instrument filters narrow the view; without them the latest valid
    production authorization known at the PIT cutoff is returned.
    """

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        recommendation_repository: RecommendationProductionAuthorizationRepository | None = None,
        allocation_repository: RecommendationProductionAllocationAuthorizationRepository | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._recommendation_repository = (
            recommendation_repository
            if recommendation_repository is not None
            else RecommendationProductionAuthorizationRepository(database=self._database)
        )
        self._allocation_repository = (
            allocation_repository
            if allocation_repository is not None
            else RecommendationProductionAllocationAuthorizationRepository(database=self._database)
        )

    def resolve_latest(
        self,
        *,
        as_of: datetime,
        symbol: str | None = None,
        instrument_id: int | None = None,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        normalized_symbol = self._optional_symbol(symbol)
        normalized_instrument_id = self._optional_instrument_id(instrument_id)

        recommendation = self._latest_recommendation(
            cutoff=cutoff,
            symbol=normalized_symbol,
            instrument_id=normalized_instrument_id,
        )
        allocation = None
        if recommendation is not None:
            allocation = self._latest_allocation(
                cutoff=cutoff,
                recommendation=recommendation,
            )

        return {
            "asOf": cutoff.isoformat(),
            "symbol": normalized_symbol,
            "instrumentId": normalized_instrument_id,
            "recommendation": recommendation,
            "allocation": allocation,
            "productionRecommendationAvailable": recommendation is not None,
            "productionAllocationAvailable": allocation is not None,
            "automaticTrading": False,
            "readOnly": True,
        }

    def _latest_recommendation(
        self,
        *,
        cutoff: datetime,
        symbol: str | None,
        instrument_id: int | None,
    ) -> dict[str, Any] | None:
        self._recommendation_repository.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT authorization_id
                FROM athena_recommendation_production_authorizations
                WHERE authorized_at <= ?
                ORDER BY authorized_at DESC, id DESC
                """,
                (cutoff.isoformat(),),
            ).fetchall()

        for row in rows:
            record = self._recommendation_repository.get(
                authorization_id=str(row["authorization_id"])
            )
            if record is None:
                continue
            authorization = record.get("authorization")
            if not isinstance(authorization, dict):
                raise ValueError("Autorización productiva persistida inválida.")
            artifact_as_of = self._aware_text(authorization.get("asOf"), "recommendation.asOf")
            authorized_at = self._aware_text(
                authorization.get("authorizedAt"), "recommendation.authorizedAt"
            )
            if artifact_as_of > cutoff or authorized_at > cutoff:
                continue
            if symbol is not None and str(authorization.get("symbol") or "").strip().upper() != symbol:
                continue
            if instrument_id is not None and self._canonical_instrument_id(
                authorization.get("instrumentId"), "recommendation.instrumentId"
            ) != instrument_id:
                continue
            self._validate_recommendation_contract(authorization)
            return authorization
        return None

    def _latest_allocation(
        self,
        *,
        cutoff: datetime,
        recommendation: dict[str, Any],
    ) -> dict[str, Any] | None:
        self._allocation_repository.initialize()
        recommendation_fp = self._sha256(
            recommendation.get("authorizationFingerprint"),
            "recommendation.authorizationFingerprint",
        )
        recommendation_instrument_id = self._canonical_instrument_id(
            recommendation.get("instrumentId"), "recommendation.instrumentId"
        )
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT authorization_id
                FROM athena_recommendation_production_allocation_authorizations
                WHERE recommendation_authorization_fingerprint = ?
                  AND authorized_at <= ?
                ORDER BY authorized_at DESC, id DESC
                """,
                (recommendation_fp, cutoff.isoformat()),
            ).fetchall()

        for row in rows:
            record = self._allocation_repository.get(
                authorization_id=str(row["authorization_id"])
            )
            if record is None:
                continue
            authorization = record.get("authorization")
            if not isinstance(authorization, dict):
                raise ValueError("Autorización productiva de allocation persistida inválida.")
            artifact_as_of = self._aware_text(authorization.get("asOf"), "allocation.asOf")
            authorized_at = self._aware_text(
                authorization.get("authorizedAt"), "allocation.authorizedAt"
            )
            if artifact_as_of > cutoff or authorized_at > cutoff:
                continue
            if authorization.get("recommendationAuthorizationFingerprint") != recommendation_fp:
                raise ValueError("Allocation productivo no corresponde a la recomendación autorizada.")
            if self._canonical_instrument_id(
                authorization.get("instrumentId"), "allocation.instrumentId"
            ) != recommendation_instrument_id:
                raise ValueError("Allocation productivo cambió instrumentId.")
            if str(authorization.get("symbol") or "").strip().upper() != str(
                recommendation.get("symbol") or ""
            ).strip().upper():
                raise ValueError("Allocation productivo cambió symbol.")
            if authorization.get("action") != recommendation.get("action"):
                raise ValueError("Allocation productivo cambió la acción autorizada.")
            if authorization.get("economicContractFingerprint") != recommendation.get(
                "economicContractFingerprint"
            ):
                raise ValueError("Allocation productivo cambió el contrato económico autorizado.")
            self._validate_allocation_contract(authorization)
            return authorization
        return None

    def _validate_recommendation_contract(self, value: dict[str, Any]) -> None:
        if value.get("status") != "production_recommendation_authorized":
            raise ValueError("Estado productivo de recomendación inválido.")
        if value.get("advisoryStatus") != "production_recommendation":
            raise ValueError("advisoryStatus productivo de recomendación inválido.")
        if value.get("recommendationCandidateReady") is not True:
            raise ValueError("La recomendación productiva no está preparada.")
        if value.get("productionEligible") is not True:
            raise ValueError("La recomendación persistida no es productiva.")
        if value.get("allocationEligible") is not False:
            raise ValueError("La recomendación no puede autorizar allocation por sí sola.")
        if value.get("automaticTrading") is not False:
            raise ValueError("El trading automático debe permanecer deshabilitado.")
        self._canonical_instrument_id(value.get("instrumentId"), "recommendation.instrumentId")
        self._sha256(value.get("authorizationFingerprint"), "authorizationFingerprint")

    def _validate_allocation_contract(self, value: dict[str, Any]) -> None:
        if value.get("status") != "production_allocation_authorized":
            raise ValueError("Estado productivo de allocation inválido.")
        if value.get("advisoryStatus") != "production_allocation":
            raise ValueError("advisoryStatus productivo de allocation inválido.")
        if value.get("productionEligible") is not True or value.get("allocationEligible") is not True:
            raise ValueError("Allocation productivo no está explícitamente autorizado.")
        for field in ("executionEligible", "orderRoutingEligible", "automaticTrading"):
            if value.get(field) is not False:
                raise ValueError(f"{field} debe permanecer deshabilitado.")
        self._canonical_instrument_id(value.get("instrumentId"), "allocation.instrumentId")
        self._sha256(value.get("authorizationFingerprint"), "authorizationFingerprint")

    def _aware(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _aware_text(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware(parsed, field)

    def _optional_symbol(self, value: str | None) -> str | None:
        if value is None:
            return None
        result = value.strip().upper()
        if not result:
            raise ValueError("symbol no puede estar vacío.")
        return result

    def _optional_instrument_id(self, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("instrument_id debe ser entero positivo.")
        return value

    def _canonical_instrument_id(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            raw = value.strip()
            if not raw or not raw.isdigit():
                raise ValueError(f"{field} debe ser entero positivo.")
            parsed = int(raw)
        else:
            raise ValueError(f"{field} debe ser entero positivo.")
        if parsed <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return parsed

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result
