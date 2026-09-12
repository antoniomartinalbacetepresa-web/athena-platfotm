from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.auth import current_account
from app.repositories.recommendation_portfolio_owner_scoped_evidence import (
    OwnerScopedPortfolioCorrelationEvidenceRepository,
    OwnerScopedPortfolioValuationEvidenceRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.portfolio_correlation_service import PortfolioCorrelationService
from app.services.portfolio_instrument_identity_service import PortfolioInstrumentIdentityService
from app.services.recommendation_authorized_allocation_pipeline_service import (
    RecommendationAuthorizedAllocationPipelineService,
)
from app.services.recommendation_portfolio_correlation_evidence_store_service import (
    RecommendationPortfolioCorrelationEvidenceStoreService,
)
from app.services.recommendation_portfolio_valuation_evidence_service import (
    RecommendationPortfolioValuationEvidenceService,
)
from app.services.recommendation_verified_allocation_pipeline_service import (
    RecommendationVerifiedAllocationPipelineService,
)


router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])
AuthenticatedAccount = Annotated[dict[str, Any], Depends(current_account)]


def _owner_user_id(account: dict[str, Any]) -> int:
    owner_user_id = account.get("id")
    if isinstance(owner_user_id, bool) or not isinstance(owner_user_id, int) or owner_user_id <= 0:
        raise RuntimeError("La cuenta autenticada carece de owner_user_id válido.")
    return owner_user_id


def _aware_payload_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} debe ser una fecha ISO con zona horaria.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} no es una fecha ISO válida.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} debe incluir zona horaria.")
    return parsed


def _safe_valuation_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact.get("portfolioValuationEvidenceReady") is not True:
        raise RuntimeError("La valoración PIT no quedó preparada.")
    if artifact.get("advisoryStatus") != "no_advice":
        raise RuntimeError("La valoración intentó emitir advice.")
    if artifact.get("productionEligible") is not False:
        raise RuntimeError("La valoración intentó habilitar producción.")
    if artifact.get("automaticTrading") is not False:
        raise RuntimeError("La valoración intentó habilitar trading automático.")
    fingerprint = str(artifact.get("portfolioValuationEvidenceFingerprint") or "")
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise RuntimeError("La valoración no expone un fingerprint SHA-256 válido.")
    return artifact


def _safe_non_advisory_allocation(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("advisoryStatus") != "no_advice":
        raise RuntimeError("Allocation violó el contrato no_advice.")
    for field in ("recommendationCandidateReady", "productionEligible", "allocationEligible", "automaticTrading"):
        if payload.get(field) is not False:
            raise RuntimeError(f"Allocation violó {field}=False.")
    if payload.get("economicContractAuthorityBoundToAllocation") is not True:
        raise RuntimeError("Allocation no quedó ligado a autoridad económica.")
    if payload.get("callerSuppliedEconomicContractAccepted") is not False:
        raise RuntimeError("Allocation aceptó un contrato económico arbitrario del caller.")
    economic_authority = payload.get("economicContractAuthority")
    if not isinstance(economic_authority, dict):
        raise RuntimeError("Allocation carece de autoridad económica verificable.")
    if economic_authority.get("resolvedFromAppendOnlyBackendAuthority") is not True:
        raise RuntimeError("Allocation no resolvió el contrato desde autoridad backend append-only.")
    fingerprint = str(economic_authority.get("economicContractFingerprint") or "")
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise RuntimeError("Allocation carece de fingerprint económico SHA-256 válido.")
    if payload.get("correlationAuthorityBoundToAllocation") is not True:
        raise RuntimeError("Allocation no quedó ligado a autoridad de correlación.")
    if payload.get("callerSuppliedCorrelationArtifactsAccepted") is not False:
        raise RuntimeError("Allocation aceptó correlación arbitraria del caller.")
    return payload


@router.get("/instrument-identity")
def get_portfolio_instrument_identity(
    account: AuthenticatedAccount,
    symbol: str = Query(..., min_length=1),
    exchange: str | None = Query(None),
) -> dict[str, object]:
    del account
    service = PortfolioInstrumentIdentityService()
    try:
        result = service.resolve(symbol=symbol, exchange=exchange)
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo resolver una identidad canónica verificable.") from exc


@router.post("/valuation-evidence")
def post_portfolio_valuation_evidence(
    account: AuthenticatedAccount,
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    service = RecommendationPortfolioValuationEvidenceService()
    try:
        owner_user_id = _owner_user_id(account)
        raw_positions = payload.get("positions")
        if not isinstance(raw_positions, list):
            raise ValueError("positions debe ser una lista.")
        base_currency = payload.get("baseCurrency")
        if not isinstance(base_currency, str):
            raise ValueError("baseCurrency debe ser una moneda ISO.")
        as_of = _aware_payload_datetime(payload.get("asOf"), "asOf")
        artifact = service.build(positions=raw_positions, base_currency=base_currency, as_of=as_of)
        if service.validate_artifact(artifact) is not artifact:
            raise RuntimeError("El validador sustituyó la evidencia de valoración.")
        safe_artifact = _safe_valuation_artifact(artifact)
        repository = OwnerScopedPortfolioValuationEvidenceRepository(
            owner_user_id=owner_user_id,
            repository=RecommendationPortfolioValuationEvidenceRepository(validator=service),
        )
        record = repository.seal(artifact=safe_artifact)
        if repository.validate_record(record) is not record:
            raise RuntimeError("El repositorio sustituyó la valoración sellada.")
        persisted = record.get("artifact")
        if persisted is not safe_artifact and persisted != safe_artifact:
            raise RuntimeError("La valoración persistida difiere del artefacto validado.")
        if not isinstance(persisted, dict):
            raise RuntimeError("La valoración persistida no respeta el contrato de ATHENA.")
        _safe_valuation_artifact(persisted)
        return {"data": persisted, "persistence": {"sealed": True, "persistedAt": record.get("persisted_at"), "recordFingerprint": record.get("record_fingerprint")}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir una valoración PIT verificable de la cartera.") from exc


@router.get("/correlation")
def get_portfolio_pair_correlation(
    account: AuthenticatedAccount,
    left_instrument_id: int = Query(..., alias="leftInstrumentId", ge=1),
    right_instrument_id: int = Query(..., alias="rightInstrumentId", ge=1),
    source_provider: str = Query(..., alias="sourceProvider", min_length=1),
    knowledge_cutoff: datetime = Query(..., alias="knowledgeCutoff"),
    observed_from: datetime | None = Query(None, alias="observedFrom"),
    observed_to: datetime | None = Query(None, alias="observedTo"),
) -> dict[str, object]:
    del account
    service = PortfolioCorrelationService()
    try:
        result = service.calculate_pair(left_instrument_id=left_instrument_id, right_instrument_id=right_instrument_id, source_provider=source_provider, knowledge_cutoff=knowledge_cutoff, observed_from=observed_from, observed_to=observed_to)
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular una correlación PIT verificable.") from exc


@router.post("/correlation-evidence")
def post_portfolio_correlation_evidence(
    account: AuthenticatedAccount,
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    try:
        owner_user_id = _owner_user_id(account)
        left = payload.get("leftInstrumentId")
        right = payload.get("rightInstrumentId")
        if isinstance(left, bool) or not isinstance(left, int) or left <= 0:
            raise ValueError("leftInstrumentId debe ser entero positivo.")
        if isinstance(right, bool) or not isinstance(right, int) or right <= 0:
            raise ValueError("rightInstrumentId debe ser entero positivo.")
        source_provider = payload.get("sourceProvider")
        if not isinstance(source_provider, str) or not source_provider.strip():
            raise ValueError("sourceProvider es obligatorio.")
        cutoff = _aware_payload_datetime(payload.get("knowledgeCutoff"), "knowledgeCutoff")
        observed_from = _aware_payload_datetime(payload.get("observedFrom"), "observedFrom") if payload.get("observedFrom") is not None else None
        observed_to = _aware_payload_datetime(payload.get("observedTo"), "observedTo") if payload.get("observedTo") is not None else None
        repository = OwnerScopedPortfolioCorrelationEvidenceRepository(owner_user_id=owner_user_id)
        result = RecommendationPortfolioCorrelationEvidenceStoreService(repository=repository).calculate_and_seal(left_instrument_id=left, right_instrument_id=right, source_provider=source_provider, knowledge_cutoff=cutoff, observed_from=observed_from, observed_to=observed_to)
        if result.get("advisoryStatus") != "no_advice":
            raise RuntimeError("La autoridad de correlación intentó emitir advice.")
        for field in ("productionEligible", "allocationEligible", "automaticTrading"):
            if result.get(field) is not False:
                raise RuntimeError(f"La autoridad de correlación violó {field}=False.")
        return {"data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo sellar evidencia PIT de correlación.") from exc


@router.post("/allocation-candidate")
def post_portfolio_allocation_candidate(
    account: AuthenticatedAccount,
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    try:
        owner_user_id = _owner_user_id(account)
        if "economicContract" in payload:
            raise ValueError("economicContract no se acepta: el backend lo resuelve desde la autoridad sellada.")
        action_fingerprint = payload.get("uncertaintyBoundActionCandidateFingerprint")
        if not isinstance(action_fingerprint, str):
            raise ValueError("uncertaintyBoundActionCandidateFingerprint es obligatorio.")
        allocation_policy_id = payload.get("allocationPolicyId")
        if not isinstance(allocation_policy_id, str) or not allocation_policy_id.strip():
            raise ValueError("allocationPolicyId es obligatorio.")
        reference_capital = payload.get("referenceCapital")
        if isinstance(reference_capital, bool) or not isinstance(reference_capital, (int, float)):
            raise ValueError("referenceCapital debe ser numérico finito y positivo.")
        reference_capital_value = float(reference_capital)
        if not math.isfinite(reference_capital_value) or reference_capital_value <= 0:
            raise ValueError("referenceCapital debe ser numérico finito y positivo.")
        base_currency = payload.get("baseCurrency")
        if not isinstance(base_currency, str):
            raise ValueError("baseCurrency debe ser una moneda ISO.")
        positions = payload.get("positions")
        if not isinstance(positions, list):
            raise ValueError("positions debe ser una lista.")
        correlation_fingerprints = payload.get("correlationEvidenceFingerprints")
        if not isinstance(correlation_fingerprints, list) or any(not isinstance(item, str) for item in correlation_fingerprints):
            raise ValueError("correlationEvidenceFingerprints debe ser una lista de fingerprints.")
        as_of = _aware_payload_datetime(payload.get("asOf"), "asOf")
        valuation_service = RecommendationPortfolioValuationEvidenceService()
        valuation_repository = OwnerScopedPortfolioValuationEvidenceRepository(
            owner_user_id=owner_user_id,
            repository=RecommendationPortfolioValuationEvidenceRepository(validator=valuation_service),
        )
        correlation_repository = OwnerScopedPortfolioCorrelationEvidenceRepository(
            owner_user_id=owner_user_id
        )
        verified_pipeline = RecommendationVerifiedAllocationPipelineService(
            valuation_service=valuation_service,
            valuation_repository=valuation_repository,
        )
        result = RecommendationAuthorizedAllocationPipelineService(
            correlation_repository=correlation_repository,
            verified_pipeline=verified_pipeline,
        ).build(uncertainty_bound_action_candidate_fingerprint=action_fingerprint, allocation_policy_id=allocation_policy_id, reference_capital=reference_capital_value, base_currency=base_currency, positions=positions, correlation_evidence_fingerprints=correlation_fingerprints, as_of=as_of)
        return {"data": _safe_non_advisory_allocation(result)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir un allocation candidate verificable.") from exc
