from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.services.recommendation_allocation_authority_resolution_service import (
    RecommendationAllocationAuthorityResolutionService,
)


router = APIRouter(
    prefix="/api/v1/portfolio",
    tags=["portfolio"],
)


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} debe ser una fecha ISO con zona horaria.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} no es una fecha ISO válida.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} debe incluir zona horaria.")
    return parsed


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} debe ser entero positivo.")
    return value


def _safe_resolution(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("advisoryStatus") != "no_advice":
        raise RuntimeError("La resolución de autoridades intentó emitir advice.")
    for field in (
        "recommendationCandidateReady",
        "productionEligible",
        "allocationEligible",
        "automaticTrading",
    ):
        if result.get(field) is not False:
            raise RuntimeError(f"La resolución de autoridades violó {field}=False.")
    if result.get("callerSuppliedInternalFingerprintsRequired") is not False:
        raise RuntimeError("La resolución exige fingerprints internos al cliente.")
    if result.get("policySelectionPerformed") is not False:
        raise RuntimeError("La resolución seleccionó una política de asignación.")
    if result.get("economicContractInvented") is not False:
        raise RuntimeError("La resolución inventó un contrato económico.")
    return result


@router.post("/allocation-authorities/resolve")
def post_portfolio_allocation_authority_resolution(
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    """Resolve exact sealed action/correlation authorities for one PIT cutoff.

    The client supplies canonical instrument IDs and the requested horizon only.
    It never supplies internal action/correlation fingerprints. Missing or
    ambiguous persisted authorities remain a non-advisory not-ready result.
    Allocation policy and economic contract stay explicit, separately persisted
    product inputs and are never selected or invented here.
    """
    try:
        instrument_id = _positive_int(payload.get("instrumentId"), "instrumentId")
        horizon_days = _positive_int(payload.get("horizonDays"), "horizonDays")
        held_raw = payload.get("heldInstrumentIds")
        if not isinstance(held_raw, list):
            raise ValueError("heldInstrumentIds debe ser una lista.")
        held_ids = [
            _positive_int(item, "heldInstrumentId")
            for item in held_raw
        ]
        as_of = _aware_datetime(payload.get("asOf"), "asOf")

        result = RecommendationAllocationAuthorityResolutionService().resolve(
            instrument_id=instrument_id,
            horizon_days=horizon_days,
            held_instrument_ids=held_ids,
            as_of=as_of,
        )
        return {"data": _safe_resolution(result)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron resolver autoridades PIT de asignación.",
        ) from exc
