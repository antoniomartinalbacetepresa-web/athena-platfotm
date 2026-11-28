from __future__ import annotations

from datetime import datetime, timezone
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_factor_exposure_repository import RecommendationFactorExposureRepository
from app.repositories.recommendation_price_factor_exposure_repository import (
    RecommendationPriceFactorExposureRepository,
)
from app.repositories.recommendation_rate_factor_exposure_repository import (
    RecommendationRateFactorExposureRepository,
)
from app.repositories.recommendation_size_factor_exposure_repository import (
    RecommendationSizeFactorExposureRepository,
)
from app.services.recommendation_market_beta_exposure_service import RecommendationMarketBetaExposureService
from app.services.recommendation_price_factor_exposure_service import (
    RecommendationPriceFactorExposureService,
)
from app.services.recommendation_rate_factor_exposure_service import (
    RecommendationRateFactorExposureService,
)
from app.services.recommendation_size_factor_exposure_service import (
    RecommendationSizeFactorExposureService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_service = RecommendationMarketBetaExposureService()
_repository = RecommendationFactorExposureRepository(service=_service)
_price_service = RecommendationPriceFactorExposureService()
_price_repository = RecommendationPriceFactorExposureRepository(service=_price_service)
_size_service = RecommendationSizeFactorExposureService()
_size_repository = RecommendationSizeFactorExposureRepository(service=_size_service)
_rate_service = RecommendationRateFactorExposureService()
_rate_repository = RecommendationRateFactorExposureRepository(service=_rate_service)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarketBetaExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    benchmarkInstrumentId: int = Field(gt=0)
    sourceProvider: str = Field(min_length=1)
    periodStart: datetime
    periodEnd: datetime
    asOf: datetime


class PriceFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    sourceProvider: str = Field(min_length=1)
    periodStart: datetime
    periodEnd: datetime
    asOf: datetime


class SizeFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    sourceProvider: str = Field(min_length=1)
    asOf: datetime


class RateFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    marketSourceProvider: str = Field(min_length=1)
    rateSeriesId: str = Field(min_length=1)
    periodStart: datetime
    periodEnd: datetime
    asOf: datetime


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_safety(persisted: dict[str, object], label: str) -> None:
    key = persisted.get("factorExposureKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail=f"{label} devolvió identidad inválida.")
    if (
        persisted.get("advisoryStatus") != "no_advice"
        or persisted.get("productionEligible") is not False
        or persisted.get("isWeightingReady") is not False
    ):
        raise HTTPException(status_code=500, detail=f"{label} violó límites de seguridad.")
    policy = persisted.get("policy")
    if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail=f"{label} intentó habilitar trading.")


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

    _assert_safety(persisted, "Market beta")
    return {"data": persisted}


@router.post("/factor-exposure/price-factors")
def post_price_factor_exposure(request: PriceFactorExposureRequest) -> dict[str, object]:
    """Derive and seal PIT momentum/low-volatility evidence; never advice or sizing."""

    try:
        artifact = _price_service.evaluate(
            instrument_id=request.instrumentId,
            source_provider=request.sourceProvider,
            period_start=_aware(request.periodStart, "periodStart"),
            period_end=_aware(request.periodEnd, "periodEnd"),
            as_of=_aware(request.asOf, "asOf"),
        )
        record = _price_repository.append(artifact=artifact)
        persisted = record["artifact"]
        if not isinstance(persisted, dict):
            raise RuntimeError("Price factor exposure persistido perdió artifact.")
        _price_service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron derivar/persistir momentum/low-volatility PIT.",
        ) from exc

    if set(persisted.get("factors", {})) != {"momentum", "low_volatility"}:
        raise HTTPException(status_code=500, detail="Price factors devolvió factores inesperados.")
    _assert_safety(persisted, "Price factors")
    return {"data": persisted}


@router.post("/factor-exposure/size")
def post_size_factor_exposure(request: SizeFactorExposureRequest) -> dict[str, object]:
    """Derive and seal bounded cross-sectional PIT size evidence; never advice or sizing."""

    try:
        artifact = _size_service.evaluate(
            instrument_id=request.instrumentId,
            source_provider=request.sourceProvider,
            as_of=_aware(request.asOf, "asOf"),
        )
        record = _size_repository.append(artifact=artifact)
        persisted = record["artifact"]
        if not isinstance(persisted, dict):
            raise RuntimeError("Size factor exposure persistido perdió artifact.")
        _size_service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo derivar/persistir size PIT.") from exc

    if set(persisted.get("factors", {})) != {"size"}:
        raise HTTPException(status_code=500, detail="Size factor devolvió factores inesperados.")
    _assert_safety(persisted, "Size factor")
    return {"data": persisted}


@router.post("/factor-exposure/rates")
def post_rate_factor_exposure(request: RateFactorExposureRequest) -> dict[str, object]:
    """Derive and seal bounded PIT rate sensitivity; never advice or sizing."""

    try:
        artifact = _rate_service.evaluate(
            instrument_id=request.instrumentId,
            market_source_provider=request.marketSourceProvider,
            rate_series_id=request.rateSeriesId,
            period_start=_aware(request.periodStart, "periodStart"),
            period_end=_aware(request.periodEnd, "periodEnd"),
            as_of=_aware(request.asOf, "asOf"),
        )
        record = _rate_repository.append(artifact=artifact)
        persisted = record["artifact"]
        if not isinstance(persisted, dict):
            raise RuntimeError("Rates factor exposure persistido perdió artifact.")
        _rate_service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo derivar/persistir rates PIT.") from exc

    if set(persisted.get("factors", {})) != {"rates"}:
        raise HTTPException(status_code=500, detail="Rates factor devolvió factores inesperados.")
    _assert_safety(persisted, "Rates factor")
    return {"data": persisted}
