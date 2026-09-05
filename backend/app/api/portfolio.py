from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.portfolio_correlation_service import PortfolioCorrelationService
from app.services.portfolio_instrument_identity_service import (
    PortfolioInstrumentIdentityService,
)
from app.services.recommendation_portfolio_valuation_evidence_service import (
    RecommendationPortfolioValuationEvidenceService,
)


router = APIRouter(
    prefix="/api/v1/portfolio",
    tags=["portfolio"],
)


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


@router.get("/instrument-identity")
def get_portfolio_instrument_identity(
    symbol: str = Query(..., min_length=1),
    exchange: str | None = Query(None),
) -> dict[str, object]:
    """Resolve one portfolio listing against ATHENA's canonical catalog.

    A unique symbol can be returned for diagnostics even when exchange identity
    is not verified. Callers must honor isRiskReady=false and must not use that
    diagnostic resolution for portfolio risk, allocation or weighting.
    """
    service = PortfolioInstrumentIdentityService()
    try:
        result = service.resolve(symbol=symbol, exchange=exchange)
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo resolver una identidad canónica verificable.",
        ) from exc


@router.post("/valuation-evidence")
def post_portfolio_valuation_evidence(
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    """Build and seal one reproducible PIT valuation of declared long positions.

    The client supplies only declared position quantity/provenance and the exact
    canonical instrument/provider identities it wants valued. Prices, currencies
    and FX are reconstructed server-side from evidence knowable at ``asOf``.
    Cash, liabilities and broker NAV are intentionally not inferred.
    """
    service = RecommendationPortfolioValuationEvidenceService()
    try:
        raw_positions = payload.get("positions")
        if not isinstance(raw_positions, list):
            raise ValueError("positions debe ser una lista.")
        base_currency = payload.get("baseCurrency")
        if not isinstance(base_currency, str):
            raise ValueError("baseCurrency debe ser una moneda ISO.")
        as_of = _aware_payload_datetime(payload.get("asOf"), "asOf")

        artifact = service.build(
            positions=raw_positions,
            base_currency=base_currency,
            as_of=as_of,
        )
        if service.validate_artifact(artifact) is not artifact:
            raise RuntimeError("El validador sustituyó la evidencia de valoración.")
        safe_artifact = _safe_valuation_artifact(artifact)

        repository = RecommendationPortfolioValuationEvidenceRepository(
            validator=service,
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

        return {
            "data": persisted,
            "persistence": {
                "sealed": True,
                "persistedAt": record.get("persisted_at"),
                "recordFingerprint": record.get("record_fingerprint"),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir una valoración PIT verificable de la cartera.",
        ) from exc


@router.get("/correlation")
def get_portfolio_pair_correlation(
    left_instrument_id: int = Query(..., alias="leftInstrumentId", ge=1),
    right_instrument_id: int = Query(..., alias="rightInstrumentId", ge=1),
    source_provider: str = Query(..., alias="sourceProvider", min_length=1),
    knowledge_cutoff: datetime = Query(..., alias="knowledgeCutoff"),
    observed_from: datetime | None = Query(None, alias="observedFrom"),
    observed_to: datetime | None = Query(None, alias="observedTo"),
) -> dict[str, object]:
    """Return descriptive PIT correlation for two canonical instruments.

    The endpoint never turns correlation into advice, allocation influence or an
    automatic-trading signal. Those policies are also carried in the payload
    returned by PortfolioCorrelationService.
    """
    service = PortfolioCorrelationService()
    try:
        result = service.calculate_pair(
            left_instrument_id=left_instrument_id,
            right_instrument_id=right_instrument_id,
            source_provider=source_provider,
            knowledge_cutoff=knowledge_cutoff,
            observed_from=observed_from,
            observed_to=observed_to,
        )
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo calcular una correlación PIT verificable.",
        ) from exc
