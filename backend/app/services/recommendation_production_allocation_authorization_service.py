from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_production_allocation_authorization_repository import (
    RecommendationProductionAllocationAuthorizationRepository,
)
from app.repositories.recommendation_production_authorization_repository import (
    RecommendationProductionAuthorizationRepository,
)
from app.services.recommendation_authorized_allocation_pipeline_service import (
    RecommendationAuthorizedAllocationPipelineService,
)


class _RecommendationAuthorizationRepository(Protocol):
    def get(self, *, authorization_id: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _AuthorizedAllocationPipeline(Protocol):
    def build(self, **kwargs: Any) -> dict[str, Any]: ...


class _AllocationAuthorizationRepository(Protocol):
    def register(self, *, authorization_draft: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationProductionAllocationAuthorizationService:
    """Offline human authorization from productive recommendation to allocation.

    The productive recommendation is resolved from its append-only backend record.
    The allocation itself is rebuilt through the existing authority-only pipeline,
    which resolves the exact sealed action, economic contract, correlations and PIT
    valuation. This boundary can authorize an allocation decision but never execution,
    order routing or automatic trading.
    """

    ARTIFACT_VERSION = "athena-production-allocation-authorization-v1"

    def __init__(
        self,
        *,
        recommendation_authorization_repository: _RecommendationAuthorizationRepository | None = None,
        authorized_allocation_pipeline: _AuthorizedAllocationPipeline | None = None,
        allocation_authorization_repository: _AllocationAuthorizationRepository | None = None,
    ) -> None:
        self._recommendation_authorization_repository = (
            recommendation_authorization_repository
            or RecommendationProductionAuthorizationRepository()
        )
        self._authorized_allocation_pipeline = (
            authorized_allocation_pipeline or RecommendationAuthorizedAllocationPipelineService()
        )
        self._allocation_authorization_repository = (
            allocation_authorization_repository
            or RecommendationProductionAllocationAuthorizationRepository()
        )

    def authorize(
        self,
        *,
        recommendation_authorization_id: str,
        allocation_authorization_id: str,
        allocation_policy_id: str,
        reference_capital: float,
        base_currency: str,
        positions: list[dict[str, Any]],
        correlation_evidence_fingerprints: list[str],
        as_of: datetime,
        operator_id: str,
        authorization_reason: str,
        human_review_confirmed: bool,
    ) -> dict[str, Any]:
        if human_review_confirmed is not True:
            raise ValueError("La autorización productiva de allocation requiere revisión humana.")
        reason = self._text(authorization_reason, "authorization_reason")
        if len(reason) < 20:
            raise ValueError("authorization_reason debe documentar la decisión de gobierno.")
        operator = self._text(operator_id, "operator_id")
        cutoff = self._aware_datetime(as_of, "as_of")
        reference = self._positive_finite(reference_capital, "reference_capital")
        currency = self._currency(base_currency, "base_currency")

        recommendation_record = self._recommendation_authorization_repository.get(
            authorization_id=self._text(
                recommendation_authorization_id, "recommendation_authorization_id"
            )
        )
        if recommendation_record is None:
            raise ValueError("La recomendación productiva no está autorizada por el backend.")
        if self._recommendation_authorization_repository.validate_record(
            recommendation_record
        ) is not recommendation_record:
            raise ValueError("El repositorio sustituyó la autorización productiva.")
        recommendation = recommendation_record.get("authorization")
        if not isinstance(recommendation, dict):
            raise ValueError("El registro productivo carece de authorization válida.")
        self._validate_productive_recommendation(recommendation, cutoff=cutoff)

        recommendation_fp = self._sha256(
            recommendation.get("authorizationFingerprint"),
            "recommendation.authorizationFingerprint",
        )
        if recommendation_record.get("authorization_fingerprint") != recommendation_fp:
            raise ValueError("El registro productivo no corresponde a su authorization fingerprint.")
        action_fp = self._sha256(
            recommendation.get("uncertaintyBoundActionCandidateFingerprint"),
            "recommendation.uncertaintyBoundActionCandidateFingerprint",
        )

        pipeline = self._authorized_allocation_pipeline.build(
            uncertainty_bound_action_candidate_fingerprint=action_fp,
            allocation_policy_id=self._text(allocation_policy_id, "allocation_policy_id"),
            reference_capital=reference,
            base_currency=currency,
            positions=positions,
            correlation_evidence_fingerprints=correlation_evidence_fingerprints,
            as_of=cutoff,
        )
        if not isinstance(pipeline, dict):
            raise ValueError("El pipeline autorizado no devolvió un artefacto válido.")
        self._validate_non_productive_pipeline(pipeline, cutoff=cutoff)
        allocation = pipeline.get("allocationCandidate")
        if not isinstance(allocation, dict):
            raise ValueError("El pipeline carece de candidato de allocation.")

        self._bind_recommendation_to_allocation(
            recommendation=recommendation,
            pipeline=pipeline,
            allocation=allocation,
            action_fingerprint=action_fp,
            reference_capital=reference,
            base_currency=currency,
            cutoff=cutoff,
        )

        correlation_authority = pipeline.get("correlationAuthority")
        if not isinstance(correlation_authority, list):
            raise ValueError("El pipeline no declaró correlationAuthority verificable.")
        correlation_fingerprints: list[str] = []
        seen: set[str] = set()
        for authority in correlation_authority:
            if not isinstance(authority, dict):
                raise ValueError("La autoridad de correlación es inválida.")
            fingerprint = self._sha256(
                authority.get("evidenceFingerprint"), "correlation.evidenceFingerprint"
            )
            if fingerprint in seen:
                raise ValueError("La autoridad de correlación contiene duplicados.")
            seen.add(fingerprint)
            correlation_fingerprints.append(fingerprint)

        draft = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "authorizationId": self._text(
                allocation_authorization_id, "allocation_authorization_id"
            ),
            "status": "production_allocation_authorized",
            "recommendationAuthorizationId": recommendation.get("authorizationId"),
            "recommendationAuthorizationFingerprint": recommendation_fp,
            "uncertaintyBoundActionCandidateFingerprint": action_fp,
            "allocationCandidateFingerprint": self._sha256(
                allocation.get("allocationCandidateFingerprint"),
                "allocation.allocationCandidateFingerprint",
            ),
            "verifiedAllocationPipelineFingerprint": self._sha256(
                pipeline.get("verifiedAllocationPipelineFingerprint"),
                "verifiedAllocationPipelineFingerprint",
            ),
            "portfolioValuationEvidenceFingerprint": self._sha256(
                pipeline.get("portfolioValuationEvidenceFingerprint"),
                "portfolioValuationEvidenceFingerprint",
            ),
            "economicContractFingerprint": self._sha256(
                allocation.get("economicContractFingerprint"),
                "allocation.economicContractFingerprint",
            ),
            "allocationPolicyId": self._text(
                allocation.get("allocationPolicyId"), "allocation.allocationPolicyId"
            ),
            "allocationPolicyFingerprint": self._sha256(
                allocation.get("allocationPolicyFingerprint"),
                "allocation.allocationPolicyFingerprint",
            ),
            "instrumentId": self._positive_int(
                allocation.get("instrumentId"), "allocation.instrumentId"
            ),
            "symbol": self._text(allocation.get("symbol"), "allocation.symbol"),
            "asOf": cutoff.isoformat(),
            "baseCurrency": currency,
            "action": self._action(allocation.get("action")),
            "policyState": self._text(allocation.get("policyState"), "allocation.policyState"),
            "referenceCapital": reference,
            "targetAmountInBaseCurrency": self._nonnegative_finite(
                allocation.get("targetAmountInBaseCurrency"),
                "allocation.targetAmountInBaseCurrency",
            ),
            "deltaAmountInBaseCurrency": self._finite(
                allocation.get("deltaAmountInBaseCurrency"),
                "allocation.deltaAmountInBaseCurrency",
            ),
            "correlationEvidenceFingerprints": correlation_fingerprints,
            "allocationCandidate": allocation,
            "operatorId": operator,
            "authorizationReason": reason,
            "humanReviewConfirmed": True,
            "authorizationMethod": "offline_local_operator",
            "advisoryStatus": "production_allocation",
            "productionEligible": True,
            "allocationEligible": True,
            "automaticAllocationPromotion": False,
            "executionEligible": False,
            "orderRoutingEligible": False,
            "automaticTrading": False,
        }
        record = self._allocation_authorization_repository.register(
            authorization_draft=draft
        )
        if not isinstance(record, dict):
            raise ValueError("El repositorio no devolvió autorización de allocation válida.")
        return record

    def _validate_productive_recommendation(
        self, recommendation: dict[str, Any], *, cutoff: datetime
    ) -> None:
        if recommendation.get("status") != "production_recommendation_authorized":
            raise ValueError("La recomendación no tiene autorización productiva.")
        if recommendation.get("advisoryStatus") != "production_recommendation":
            raise ValueError("La recomendación productiva cambió advisoryStatus.")
        if recommendation.get("recommendationCandidateReady") is not True:
            raise ValueError("La recomendación productiva no está preparada.")
        if recommendation.get("productionEligible") is not True:
            raise ValueError("La recomendación no está habilitada para producción.")
        if recommendation.get("allocationEligible") is not False:
            raise ValueError("La recomendación intentó autorizar allocation por sí sola.")
        if recommendation.get("automaticTrading") is not False:
            raise ValueError("La recomendación intentó habilitar trading automático.")
        if recommendation.get("humanReviewConfirmed") is not True:
            raise ValueError("La recomendación productiva carece de revisión humana.")
        if self._aware_datetime(recommendation.get("asOf"), "recommendation.asOf") != cutoff:
            raise ValueError("La recomendación y el allocation no comparten el mismo corte PIT.")

    def _validate_non_productive_pipeline(
        self, pipeline: dict[str, Any], *, cutoff: datetime
    ) -> None:
        if pipeline.get("advisoryStatus") != "no_advice":
            raise ValueError("El pipeline fuente debe permanecer no_advice.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "allocationEligible",
            "automaticTrading",
        ):
            if pipeline.get(field) is not False:
                raise ValueError(f"El pipeline fuente violó {field}=False.")
        if self._aware_datetime(pipeline.get("asOf"), "pipeline.asOf") != cutoff:
            raise ValueError("El pipeline cambió el corte PIT.")
        if pipeline.get("economicContractAuthorityBoundToAllocation") is not True:
            raise ValueError("El pipeline no ligó la autoridad económica al allocation.")
        if pipeline.get("correlationAuthorityBoundToAllocation") is not True:
            raise ValueError("El pipeline no ligó la autoridad de correlación al allocation.")
        if pipeline.get("callerSuppliedEconomicContractAccepted") is not False:
            raise ValueError("El pipeline aceptó contrato económico del caller.")
        if pipeline.get("callerSuppliedCorrelationArtifactsAccepted") is not False:
            raise ValueError("El pipeline aceptó correlación JSON del caller.")
        if pipeline.get("portfolioValuationSealedBeforeAllocation") is not True:
            raise ValueError("La valoración PIT no fue sellada antes del allocation.")

    def _bind_recommendation_to_allocation(
        self,
        *,
        recommendation: dict[str, Any],
        pipeline: dict[str, Any],
        allocation: dict[str, Any],
        action_fingerprint: str,
        reference_capital: float,
        base_currency: str,
        cutoff: datetime,
    ) -> None:
        if pipeline.get("uncertaintyBoundActionCandidateFingerprint") != action_fingerprint:
            raise ValueError("El pipeline cambió la acción productiva autorizada.")
        if allocation.get("uncertaintyBoundActionCandidateFingerprint") != action_fingerprint:
            raise ValueError("El allocation cambió la acción productiva autorizada.")
        if self._positive_int(allocation.get("instrumentId"), "allocation.instrumentId") != self._positive_int(recommendation.get("instrumentId"), "recommendation.instrumentId"):
            raise ValueError("El allocation cambió instrumentId respecto a la recomendación.")
        if self._text(allocation.get("symbol"), "allocation.symbol") != self._text(recommendation.get("symbol"), "recommendation.symbol"):
            raise ValueError("El allocation cambió symbol respecto a la recomendación.")
        if self._action(allocation.get("action")) != self._action(recommendation.get("action")):
            raise ValueError("El allocation cambió la acción productiva autorizada.")
        if self._text(allocation.get("policyState"), "allocation.policyState") != self._text(recommendation.get("policyState"), "recommendation.policyState"):
            raise ValueError("El allocation cambió el estado de cartera autorizado.")
        if self._sha256(allocation.get("economicContractFingerprint"), "allocation.economicContractFingerprint") != self._sha256(recommendation.get("economicContractFingerprint"), "recommendation.economicContractFingerprint"):
            raise ValueError("El allocation cambió el contrato económico autorizado.")
        if self._aware_datetime(allocation.get("asOf"), "allocation.asOf") != cutoff:
            raise ValueError("El allocation cambió el corte PIT.")
        if self._currency(allocation.get("baseCurrency"), "allocation.baseCurrency") != base_currency:
            raise ValueError("El allocation cambió la moneda base.")
        if not math.isclose(
            self._positive_finite(allocation.get("referenceCapital"), "allocation.referenceCapital"),
            reference_capital,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("El allocation cambió el capital de referencia.")
        if allocation.get("status") != "allocation_candidate_non_advisory":
            raise ValueError("El allocation fuente no tiene el estado esperado.")
        if allocation.get("allocationEvidenceStructurallyReady") is not True:
            raise ValueError("La evidencia estructural del allocation no está preparada.")
        if allocation.get("advisoryStatus") != "no_advice":
            raise ValueError("El allocation fuente debe permanecer no_advice.")
        for field in ("productionEligible", "allocationEligible", "automaticTrading"):
            if allocation.get(field) is not False:
                raise ValueError(f"El allocation fuente violó {field}=False.")

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _action(self, value: object) -> str:
        result = self._text(value, "action").lower()
        if result not in {"buy", "hold", "reduce", "sell"}:
            raise ValueError("action no soportada.")
        return result

    def _currency(self, value: object, field: str) -> str:
        result = self._text(value, field).upper()
        if len(result) != 3 or not result.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _aware_datetime(self, value: object, field: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{field} debe ser ISO-8601 con zona horaria.") from exc
        else:
            raise ValueError(f"{field} debe ser ISO-8601 con zona horaria.")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _nonnegative_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0:
            raise ValueError(f"{field} no puede ser negativo.")
        return result
