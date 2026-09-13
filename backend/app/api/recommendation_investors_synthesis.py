from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.recommendation_news_synthesis import _radar_from_cycle_record
from app.repositories.recommendation_investors_synthesis_repository import RecommendationInvestorsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_investors_synthesis_service import InvestorsModelAssessmentInput, RecommendationInvestorsSynthesisService


router = APIRouter(prefix="/api/v1/recommendations/professional-research", tags=["recommendations-investors-synthesis"])
cycle_repository = RecommendationProfessionalResearchCycleRepository()
synthesis_repository = RecommendationInvestorsSynthesisRepository()
synthesis_service = RecommendationInvestorsSynthesisService()


class InvestorsAssessmentRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    modelProvider: str = Field(min_length=1)
    modelName: str = Field(min_length=1)
    modelVersion: str = Field(min_length=1)
    inputFingerprint: str = Field(min_length=64, max_length=64)
    generatedAt: datetime
    summary: str = Field(min_length=1, max_length=4000)
    importance: str = Field(min_length=1)
    impactDirection: str = Field(min_length=1)
    impactMagnitude: float
    confidence: float


class InvestorsSynthesisRequest(BaseModel):
    assessments: list[InvestorsAssessmentRequest] = Field(min_length=1, max_length=200)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("generatedAt debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _persistence(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "appendOnly": True,
        "packageIntegrityVerified": True,
        "synthesisHash": record["synthesis_hash"],
        "cycleHash": record["cycle_hash"],
        "radarHash": record["radar_hash"],
        "createdAt": record["created_at"],
        "storageClaim": "single_canonical_investors_synthesis_per_cycle_append_only_not_worm_storage",
    }


@router.post("/research-cycle/{cycle_hash}/investors-synthesis")
def post_investors_synthesis(cycle_hash: str, request: InvestorsSynthesisRequest) -> dict[str, Any]:
    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        radar = _radar_from_cycle_record(cycle_record)
        result = synthesis_service.build(
            radar_result=radar,
            assessments=tuple(
                InvestorsModelAssessmentInput(
                    evidence_id=item.evidenceId,
                    model_provider=item.modelProvider,
                    model_name=item.modelName,
                    model_version=item.modelVersion,
                    input_fingerprint=item.inputFingerprint,
                    generated_at=_aware(item.generatedAt),
                    summary=item.summary,
                    importance=item.importance,
                    impact_direction=item.impactDirection,
                    impact_magnitude=item.impactMagnitude,
                    confidence=item.confidence,
                )
                for item in request.assessments
            ),
        )
        payload = result.to_api_dict()
        record = synthesis_repository.append(
            cycle_hash=str(cycle_record["cycle_hash"]),
            radar_hash=str(cycle_record["radar_hash"]),
            synthesis_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo validar y persistir Investors synthesis.") from exc
    return {
        "data": {
            "cycleBindingVerified": True,
            "cycleHash": cycle_record["cycle_hash"],
            "radarHash": cycle_record["radar_hash"],
            "synthesis": payload,
            "persistence": _persistence(record),
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }
    }


@router.get("/research-cycle/{cycle_hash}/investors-synthesis")
def get_investors_synthesis(cycle_hash: str) -> dict[str, Any]:
    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        _radar_from_cycle_record(cycle_record)
        record = synthesis_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
        if record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("Investors synthesis ya no coincide con el radarHash del ciclo.")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar Investors synthesis persistida.") from exc
    return {
        "data": {
            "cycleBindingVerified": True,
            "cycleHash": cycle_record["cycle_hash"],
            "radarHash": cycle_record["radar_hash"],
            "synthesis": record["package"]["synthesis"],
            "persistence": _persistence(record),
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }
    }
