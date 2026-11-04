from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.recommendation_research_forecast_evaluation import (
    ProspectiveEvaluationSpecificationRequest,
    _persist_evaluation_specification,
    cycle_repository,
)
from app.services.persisted_forecast_input_manifest_service import PersistedForecastInputManifestService


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
manifest_service = PersistedForecastInputManifestService()


class PersistedMarketSelectionRequest(BaseModel):
    instrumentId: int = Field(gt=0)
    sourceProvider: str = Field(min_length=1, max_length=100)
    observedAt: datetime


class PersistedPitForecastRequest(ProspectiveEvaluationSpecificationRequest):
    macroObservationKeys: list[str] = Field(default_factory=list, max_length=200)
    marketObservations: list[PersistedMarketSelectionRequest] = Field(default_factory=list, max_length=200)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.post("/research-cycle/{cycle_hash}/persisted-pit-evaluation-specification")
def post_persisted_pit_evaluation_specification(
    cycle_hash: str,
    request: PersistedPitForecastRequest,
) -> dict[str, object]:
    """Seal v3 from re-resolvable persisted macro and/or market observations."""
    period_start = _aware_utc(request.periodStart, "periodStart")
    available_at = _aware_utc(request.availableAt, "availableAt")
    market_selections = [
        {
            "instrumentId": item.instrumentId,
            "sourceProvider": item.sourceProvider,
            "observedAt": _aware_utc(item.observedAt, f"marketObservations[{index}].observedAt"),
        }
        for index, item in enumerate(request.marketObservations)
    ]
    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        cycle = cycle_record["package"]["cycle"]
        cutoff = datetime.fromisoformat(cycle["asOf"])
        inputs = manifest_service.resolve(
            macro_observation_keys=request.macroObservationKeys,
            market_selections=market_selections,
            knowledge_cutoff=cutoff,
            forecast_available_at=available_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron verificar inputs PIT persistidos.",
        ) from exc
    return _persist_evaluation_specification(
        cycle_hash,
        request,
        period_start=period_start,
        input_evidence=inputs,
    )
