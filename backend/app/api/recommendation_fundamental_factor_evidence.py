from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_book_to_market_evidence_repository import (
    RecommendationBookToMarketEvidenceRepository,
)
from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_service = RecommendationBookToMarketEvidenceService()
_repository = RecommendationBookToMarketEvidenceRepository(service=_service)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BookToMarketEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    asOf: datetime


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


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
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(float(ratio)) or float(ratio) <= 0:
        raise HTTPException(status_code=500, detail="Book-to-market devolvió ratio inválido.")


@router.post("/factor-evidence/book-to-market")
def post_book_to_market_evidence(request: BookToMarketEvidenceRequest) -> dict[str, object]:
    """Resolve issuer-bound PIT book-to-market evidence; never a value score or advice."""

    try:
        artifact = _service.evaluate(
            instrument_id=request.instrumentId,
            as_of=_aware(request.asOf, "asOf"),
        )
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
