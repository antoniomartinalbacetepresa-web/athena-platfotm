from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_book_to_market_evidence_repository import (
    RecommendationBookToMarketEvidenceRepository,
)
from app.repositories.recommendation_operating_margin_evidence_repository import (
    RecommendationOperatingMarginEvidenceRepository,
)
from app.repositories.recommendation_quality_factor_exposure_repository import (
    RecommendationQualityFactorExposureRepository,
)
from app.repositories.recommendation_value_factor_exposure_repository import (
    RecommendationValueFactorExposureRepository,
)
from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)
from app.services.recommendation_operating_margin_evidence_service import (
    RecommendationOperatingMarginEvidenceService,
)
from app.services.recommendation_quality_factor_exposure_service import (
    RecommendationQualityFactorExposureService,
)
from app.services.recommendation_value_factor_exposure_service import (
    RecommendationValueFactorExposureService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_service = RecommendationBookToMarketEvidenceService()
_repository = RecommendationBookToMarketEvidenceRepository(service=_service)
_value_service = RecommendationValueFactorExposureService()
_value_repository = RecommendationValueFactorExposureRepository(service=_value_service)
_margin_service = RecommendationOperatingMarginEvidenceService()
_margin_repository = RecommendationOperatingMarginEvidenceRepository(service=_margin_service)
_quality_service = RecommendationQualityFactorExposureService()
_quality_repository = RecommendationQualityFactorExposureRepository(service=_quality_service)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BookToMarketEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    asOf: datetime


class ValueFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    asOf: datetime


class OperatingMarginEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    asOf: datetime


class QualityFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    asOf: datetime


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _finite(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("module") != "book_to_market_pit_evidence":
        raise HTTPException(status_code=500, detail="Book-to-market devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Book-to-market violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Book-to-market intentó habilitar producción/weighting.")
    if payload.get("factorReady") is not False or payload.get("factorExposure") is not None:
        raise HTTPException(status_code=500, detail="Book-to-market bruto intentó presentarse como factor.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Book-to-market devolvió política inválida.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Book-to-market intentó habilitar automatización.")
    if policy.get("normalization") != "not_yet_cross_sectionally_ranked":
        raise HTTPException(status_code=500, detail="Book-to-market perdió límite de normalización.")
    status = payload.get("status")
    if status == "missing":
        if payload.get("evidenceKey") is not None or payload.get("bookToMarket") is not None:
            raise HTTPException(status_code=500, detail="Book-to-market missing contiene valor inventado.")
        return
    if status != "resolved":
        raise HTTPException(status_code=500, detail="Book-to-market devolvió estado inválido.")
    key = payload.get("evidenceKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Book-to-market devolvió identidad inválida.")
    ratio = payload.get("bookToMarket")
    if not _finite(ratio) or float(ratio) <= 0:
        raise HTTPException(status_code=500, detail="Book-to-market devolvió ratio inválido.")


def _assert_value_contract(payload: dict[str, object]) -> None:
    _assert_factor_contract(payload, module="pit_value_factor_exposure", factor="value")


def _assert_margin_contract(payload: dict[str, object]) -> None:
    if payload.get("module") != "operating_margin_pit_evidence":
        raise HTTPException(status_code=500, detail="Operating margin devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Operating margin violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Operating margin intentó habilitar producción/weighting.")
    if payload.get("factorReady") is not False or payload.get("factorExposure") is not None:
        raise HTTPException(status_code=500, detail="Operating margin bruto intentó presentarse como factor.")
    policy = payload.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("automaticTrading") is not False
        or policy.get("automaticProductionPromotion") is not False
        or policy.get("qualityDefinition") != "single_metric_operating_margin_not_composite_quality"
        or policy.get("sectorNeutralization") != "not_performed_or_claimed"
    ):
        raise HTTPException(status_code=500, detail="Operating margin perdió contrato metodológico/de seguridad.")
    status = payload.get("status")
    if status == "missing":
        if payload.get("evidenceKey") is not None or payload.get("operatingMargin") is not None:
            raise HTTPException(status_code=500, detail="Operating margin missing contiene valor inventado.")
        return
    if status != "resolved":
        raise HTTPException(status_code=500, detail="Operating margin devolvió estado inválido.")
    key = payload.get("evidenceKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Operating margin devolvió identidad inválida.")
    if not _finite(payload.get("operatingMargin")):
        raise HTTPException(status_code=500, detail="Operating margin devolvió valor no finito.")


def _assert_factor_contract(payload: dict[str, object], *, module: str, factor: str) -> None:
    if payload.get("module") != module:
        raise HTTPException(status_code=500, detail=f"{factor} factor devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail=f"{factor} factor violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail=f"{factor} factor intentó habilitar producción/weighting.")
    key = payload.get("factorExposureKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail=f"{factor} factor devolvió identidad inválida.")
    factors = payload.get("factors")
    if not isinstance(factors, dict) or set(factors) != {factor}:
        raise HTTPException(status_code=500, detail=f"{factor} factor devolvió factores inesperados.")
    value = factors.get(factor)
    if not _finite(value):
        raise HTTPException(status_code=500, detail=f"{factor} factor devolvió exposición no finita.")
    if float(value) < -1.0 - 1e-12 or float(value) > 1.0 + 1e-12:
        raise HTTPException(status_code=500, detail=f"{factor} factor salió de [-1,1].")
    policy = payload.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("automaticTrading") is not False
        or policy.get("automaticProductionPromotion") is not False
        or policy.get("thresholds") != "not_calibrated"
    ):
        raise HTTPException(status_code=500, detail=f"{factor} factor perdió límites de seguridad/calibración.")


def _assert_quality_contract(payload: dict[str, object]) -> None:
    _assert_factor_contract(payload, module="pit_quality_factor_exposure", factor="quality")
    policy = payload.get("policy")
    assert isinstance(policy, dict)
    if (
        policy.get("qualityDefinition") != "single_metric_operating_margin_not_composite_quality"
        or policy.get("sectorNeutralization") != "not_performed_or_claimed"
    ):
        raise HTTPException(status_code=500, detail="Quality factor perdió metodología explícita.")


@router.post("/factor-evidence/book-to-market")
def post_book_to_market_evidence(request: BookToMarketEvidenceRequest) -> dict[str, object]:
    try:
        artifact = _service.evaluate(instrument_id=request.instrumentId, as_of=_aware(request.asOf, "asOf"))
        _assert_contract(artifact)
        if artifact.get("status") == "resolved":
            record = _repository.append(artifact=artifact)
            persisted = record.get("artifact")
            if not isinstance(persisted, dict):
                raise RuntimeError("Book-to-market persistido perdió artifact.")
            _service.validate_artifact(persisted)
            artifact = persisted
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo resolver/persistir book-to-market PIT.") from exc
    _assert_contract(artifact)
    return {"data": artifact}


@router.post("/factor-exposure/value")
def post_value_factor_exposure(request: ValueFactorExposureRequest) -> dict[str, object]:
    try:
        artifact = _value_service.evaluate(instrument_id=request.instrumentId, as_of=_aware(request.asOf, "asOf"))
        record = _value_repository.append(artifact=artifact)
        persisted = record.get("artifact")
        if not isinstance(persisted, dict):
            raise RuntimeError("Value factor persistido perdió artifact.")
        _value_service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo derivar/persistir value PIT.") from exc
    _assert_value_contract(persisted)
    return {"data": persisted}


@router.post("/factor-evidence/operating-margin")
def post_operating_margin_evidence(request: OperatingMarginEvidenceRequest) -> dict[str, object]:
    """Resolve same-filing annual operating margin PIT evidence; never a quality score."""
    try:
        artifact = _margin_service.evaluate(instrument_id=request.instrumentId, as_of=_aware(request.asOf, "asOf"))
        _assert_margin_contract(artifact)
        if artifact.get("status") == "resolved":
            record = _margin_repository.append(artifact=artifact)
            persisted = record.get("artifact")
            if not isinstance(persisted, dict):
                raise RuntimeError("Operating margin persistido perdió artifact.")
            _margin_service.validate_artifact(persisted)
            artifact = persisted
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo resolver/persistir operating margin PIT.") from exc
    _assert_margin_contract(artifact)
    return {"data": artifact}


@router.post("/factor-exposure/quality")
def post_quality_factor_exposure(request: QualityFactorExposureRequest) -> dict[str, object]:
    """Derive issuer-deduplicated bounded PIT quality exposure from annual operating margin."""
    try:
        artifact = _quality_service.evaluate(instrument_id=request.instrumentId, as_of=_aware(request.asOf, "asOf"))
        record = _quality_repository.append(artifact=artifact)
        persisted = record.get("artifact")
        if not isinstance(persisted, dict):
            raise RuntimeError("Quality factor persistido perdió artifact.")
        _quality_service.validate_artifact(persisted)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo derivar/persistir quality PIT.") from exc
    _assert_quality_contract(persisted)
    return {"data": persisted}
