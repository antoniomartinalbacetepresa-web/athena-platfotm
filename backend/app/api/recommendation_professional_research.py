from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_expectations_gap_service import (
    RecommendationExpectationsGapService,
)
from app.services.recommendation_reverse_valuation_service import (
    RecommendationReverseValuationService,
)
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

valuation_service = RecommendationValuationSignalService()
reverse_valuation_service = RecommendationReverseValuationService(
    valuation_service=valuation_service,
)
expectations_gap_service = RecommendationExpectationsGapService(
    reverse_valuation_service=reverse_valuation_service,
)


def _effective_as_of(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return result.astimezone(timezone.utc)


def _payload(result: object, *, label: str) -> dict[str, object]:
    to_api_dict = getattr(result, "to_api_dict", None)
    if not callable(to_api_dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió un contrato inválido.")
    payload = to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió un contrato inválido.")
    return dict(payload)


def _assert_research_contract(payload: dict[str, object], *, label: str) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail=f"{label} violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail=f"{label} intentó habilitar producción.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail=f"{label} intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") not in (None, False):
        raise HTTPException(status_code=500, detail=f"{label} intentó promover producción automáticamente.")


def _assert_expectations_contract(payload: dict[str, object]) -> None:
    _assert_research_contract(payload, label="Expectations Gap")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="Expectations Gap intentó declararse listo para ponderación.",
        )
    reference = payload.get("referenceExpectation")
    if not isinstance(reference, dict):
        raise HTTPException(status_code=500, detail="Expectations Gap perdió la evidencia de referencia.")
    required = ("kind", "metric", "horizonYears", "availableAt", "source", "sourceRef")
    if any(reference.get(field) in (None, "") for field in required):
        raise HTTPException(
            status_code=500,
            detail="Expectations Gap devolvió evidencia PIT incompleta.",
        )


@router.get("/reverse-valuation")
def get_reverse_valuation(
    symbol: str = Query(..., min_length=1),
    horizon_years: int = Query(..., ge=1, le=50, alias="horizonYears"),
    required_return: float = Query(..., gt=-1.0, le=2.0, alias="requiredReturn"),
    exit_pe: float = Query(..., gt=0.0, le=500.0, alias="exitPe"),
    as_of: datetime | None = Query(None, alias="asOf"),
) -> dict[str, object]:
    """Expose an explicit PIT reverse-valuation diagnostic without advice."""

    effective_as_of = _effective_as_of(as_of)
    try:
        result = reverse_valuation_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
            horizon_years=horizon_years,
            required_return=required_return,
            exit_pe=exit_pe,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir la valoración inversa PIT de ATHENA.",
        ) from exc

    payload = _payload(result, label="Reverse Valuation")
    _assert_research_contract(payload, label="Reverse Valuation")
    return {"data": payload}


@router.get("/expectations-gap")
def get_expectations_gap(
    symbol: str = Query(..., min_length=1),
    horizon_years: int = Query(..., ge=1, le=50, alias="horizonYears"),
    required_return: float = Query(..., gt=-1.0, le=2.0, alias="requiredReturn"),
    exit_pe: float = Query(..., gt=0.0, le=500.0, alias="exitPe"),
    reference_eps_cagr: float = Query(..., gt=-1.0, le=10.0, alias="referenceEpsCagr"),
    expectation_kind: str = Query(..., min_length=1, alias="expectationKind"),
    expectation_metric: str = Query(..., min_length=1, alias="expectationMetric"),
    expectation_horizon_years: int = Query(..., ge=1, le=50, alias="expectationHorizonYears"),
    expectation_available_at: datetime = Query(..., alias="expectationAvailableAt"),
    expectation_source: str = Query(..., min_length=1, alias="expectationSource"),
    expectation_source_ref: str = Query(..., min_length=1, alias="expectationSourceRef"),
    as_of: datetime | None = Query(None, alias="asOf"),
) -> dict[str, object]:
    """Compare one typed PIT expectation with price-implied growth, research-only."""

    effective_as_of = _effective_as_of(as_of)
    try:
        result = expectations_gap_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
            horizon_years=horizon_years,
            required_return=required_return,
            exit_pe=exit_pe,
            reference_eps_cagr=reference_eps_cagr,
            expectation_kind=expectation_kind,
            expectation_metric=expectation_metric,
            expectation_horizon_years=expectation_horizon_years,
            expectation_available_at=expectation_available_at,
            expectation_source=expectation_source,
            expectation_source_ref=expectation_source_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir Expectations Gap PIT de ATHENA.",
        ) from exc

    payload = _payload(result, label="Expectations Gap")
    _assert_expectations_contract(payload)
    return {"data": payload}
