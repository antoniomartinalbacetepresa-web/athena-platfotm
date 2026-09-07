from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

factor_risk_service = RecommendationFactorRiskService()


class FactorRiskPositionRequest(BaseModel):
    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class FactorRiskResearchRequest(BaseModel):
    asOf: datetime
    positions: list[FactorRiskPositionRequest] = Field(min_length=1, max_length=500)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Factor Risk violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar ponderación.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó promover producción automáticamente.")
    if policy.get("identity") != "duplicate_instrument_or_symbol_forbidden":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía de identidad.")
    if policy.get("fx") != "usd_fx_is_explicit_factor_not_silently_netting_currency_risk":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía explícita de FX.")
    if policy.get("missingFactorCoverage") != "reported_explicitly_never_imputed_as_zero":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía contra imputación silenciosa.")
    if policy.get("thresholds") != "not_calibrated":
        raise HTTPException(status_code=500, detail="Factor Risk intentó usar umbrales no calibrados.")

    count = payload.get("positionCount")
    invested = payload.get("investedWeight")
    cash = payload.get("cashWeight")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió positionCount inválido.")
    for value in (
        invested,
        cash,
        payload.get("grossFactorExposure"),
        payload.get("maxAbsoluteFactorExposure"),
    ):
        if not _finite_number(value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió métricas no finitas.")
    if abs(float(invested) + float(cash) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió pesos de cartera incoherentes.")

    exposures = payload.get("weightedExposures")
    coverage = payload.get("factorCoverageWeights")
    fully_covered = payload.get("fullyCoveredFactors")
    if not isinstance(exposures, dict) or not isinstance(coverage, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió exposiciones/cobertura inválidas.")
    if set(exposures) != set(coverage):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura factorial incompleta.")
    for name, value in exposures.items():
        if not isinstance(name, str) or not _finite_number(value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió exposición no finita.")
        coverage_value = coverage.get(name)
        if not _finite_number(coverage_value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura no finita.")
        if float(coverage_value) < -1e-12 or float(coverage_value) > float(invested) + 1e-9:
            raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura fuera de rango.")
    if not isinstance(fully_covered, list) or any(
        not isinstance(name, str) or name not in exposures for name in fully_covered
    ):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió fullyCoveredFactors inválido.")
    expected_fully_covered = {
        name
        for name, value in coverage.items()
        if float(invested) > 0.0 and abs(float(value) - float(invested)) <= 1e-9
    }
    if set(fully_covered) != expected_fully_covered:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura completa incoherente.")

    positions = payload.get("positions")
    if not isinstance(positions, list) or len(positions) != count:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia de posiciones inválida.")
    seen_ids: set[int] = set()
    seen_symbols: set[str] = set()
    for position in positions:
        if not isinstance(position, dict):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia PIT inválida.")
        instrument_id = position.get("instrumentId")
        symbol = position.get("symbol")
        source = position.get("source")
        source_ref = position.get("sourceRef")
        available_at = position.get("exposureAvailableAt")
        factors = position.get("factors")
        weight = position.get("weight")
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or instrument_id <= 0
            or not isinstance(symbol, str)
            or not symbol.strip()
            or not isinstance(source, str)
            or not source.strip()
            or not isinstance(source_ref, str)
            or not source_ref.strip()
            or not isinstance(available_at, str)
            or not available_at.strip()
            or not isinstance(factors, dict)
            or not factors
            or not _finite_number(weight)
        ):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió provenance PIT incompleta.")
        normalized_symbol = symbol.strip().upper()
        if instrument_id in seen_ids or normalized_symbol in seen_symbols:
            raise HTTPException(status_code=500, detail="Factor Risk devolvió identidad duplicada.")
        seen_ids.add(instrument_id)
        seen_symbols.add(normalized_symbol)
        for factor, value in factors.items():
            if not isinstance(factor, str) or factor not in exposures or not _finite_number(value):
                raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia factorial inválida.")

    dominant = payload.get("dominantFactor")
    if dominant is not None and (
        not isinstance(dominant, str) or dominant not in set(fully_covered)
    ):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió dominantFactor sin cobertura completa.")


@router.post("/factor-risk")
def post_factor_risk(request: FactorRiskResearchRequest) -> dict[str, object]:
    """Measure explicit PIT portfolio factor exposure without sizing or trade advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    positions: list[FactorRiskPositionInput] = []
    for item in request.positions:
        positions.append(
            FactorRiskPositionInput(
                instrument_id=item.instrumentId,
                symbol=item.symbol,
                weight=item.weight,
                exposure_available_at=_aware_utc(
                    item.exposureAvailableAt,
                    "positions.exposureAvailableAt",
                ),
                source=item.source,
                source_ref=item.sourceRef,
                factors=dict(item.factors),
            )
        )

    try:
        result = factor_risk_service.evaluate(
            as_of=as_of,
            positions=tuple(positions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar Factor Risk PIT de ATHENA.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}
