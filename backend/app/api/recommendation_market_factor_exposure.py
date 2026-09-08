from __future__ import annotations

from datetime import datetime, timezone
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_factor_exposure_repository import RecommendationFactorExposureRepository
from app.services.recommendation_market_beta_exposure_service import RecommendationMarketBetaExposureService


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_service = RecommendationMarketBetaExposureService()
_repository = RecommendationFactorExposureRepository(service=_service)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarketBetaExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    benchmarkInstrumentId: int = Field(gt=0)
    sourceProvider: str = Field(min_length=1)
    periodStart: datetime
    periodEnd: datetime
    asOf: datetime


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.post("/factor-exposure/market-beta")
def post_market_beta_exposure(request: MarketBetaExposureRequest) -> dict[str, object]:
    """Derive and seal a PIT market-beta exposure; never advice or sizing."""

    try:
        artifact = _service.evaluate(
            instrument_id=request.instrumentId,
            benchmark_instrument_id=request.benchmarkInstrumentId,
            source_provider=request.sourceProvider,
            period_start=_aware(request.periodStart, "periodStart"),
            period_end=_aware(request.periodEnd, "periodEnd"),
            as_of=_aware(request.asOf, "asOf"),
        )
        record = _repository.append(artifact=artifact)
        persisted = record["artifact"]
        if not isinstance(persisted, dict):
            raise RuntimeError("Factor exposure persistido perdió artifact.")
        _service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo derivar/persistir beta PIT.") from exc

    key = persisted.get("factorExposureKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Market beta devolvió identidad inválida.")
    if (
        persisted.get("advisoryStatus") != "no_advice"
        or persisted.get("productionEligible") is not False
        or persisted.get("isWeightingReady") is not False
    ):
        raise HTTPException(status_code=500, detail="Market beta violó límites de seguridad.")
    policy = persisted.get("policy")
    if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Market beta intentó habilitar trading.")
    return {"data": persisted}
