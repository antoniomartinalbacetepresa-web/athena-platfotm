from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_nlv_snapshot_repository import (
    RecommendationPortfolioNlvSnapshotRepository,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_repository = RecommendationPortfolioNlvSnapshotRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE = "total_net_liquidation_value_in_reporting_currency"


class PortfolioNlvSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    value: float
    observedAt: datetime
    availableAt: datetime
    phase: str = Field(min_length=1)
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    asOf: datetime


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_artifact(artifact: dict[str, object]) -> None:
    key = artifact.get("snapshotKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="NLV snapshot devolvió snapshotKey inválida.")
    value = artifact.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise HTTPException(status_code=500, detail="NLV snapshot devolvió valor no finito.")
    if float(value) < 0.0:
        raise HTTPException(status_code=500, detail="NLV snapshot devolvió valor negativo.")
    if artifact.get("valuationScope") != _SCOPE:
        raise HTTPException(status_code=500, detail="NLV snapshot perdió alcance total.")
    if artifact.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="NLV snapshot violó no_advice.")
    if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="NLV snapshot intentó habilitar producción/weighting.")
    policy = artifact.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="NLV snapshot perdió policy.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="NLV snapshot intentó habilitar automatización.")
    for field in ("cashInference", "liabilityInference", "unsettledInference", "fxInference"):
        if policy.get(field) != "forbidden":
            raise HTTPException(status_code=500, detail=f"NLV snapshot permitió {field}.")


@router.post("/portfolio-nlv-snapshots")
def post_portfolio_nlv_snapshot(request: PortfolioNlvSnapshotRequest) -> dict[str, object]:
    """Persist independently observed full-NLV PIT evidence; never infer missing balance-sheet components."""

    try:
        record = _repository.append(
            portfolio_id=request.portfolioId,
            reporting_currency=request.reportingCurrency,
            value=request.value,
            observed_at=_aware_utc(request.observedAt, "observedAt"),
            available_at=_aware_utc(request.availableAt, "availableAt"),
            phase=request.phase,
            source=request.source,
            source_ref=request.sourceRef,
            as_of=_aware_utc(request.asOf, "asOf"),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo persistir el snapshot NLV PIT.") from exc
    artifact = record["artifact"]
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="NLV persistido carece de artifact válido.")
    _assert_artifact(artifact)
    return {
        "data": artifact,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }


@router.get("/portfolio-nlv-snapshots/{snapshot_key}")
def get_portfolio_nlv_snapshot(snapshot_key: str) -> dict[str, object]:
    """Read one persisted NLV snapshot after full tamper verification."""

    try:
        record = _repository.get_by_key(snapshot_key=snapshot_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    artifact = record["artifact"]
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="NLV persistido carece de artifact válido.")
    _assert_artifact(artifact)
    return {
        "data": artifact,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }
