from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_news_synthesis_repository import (
    RecommendationNewsSynthesisRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    AthenaRadarResult,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_news_synthesis_service import (
    NewsModelAssessmentInput,
    RecommendationNewsSynthesisService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-news-synthesis"],
)

cycle_repository = RecommendationProfessionalResearchCycleRepository()
synthesis_repository = RecommendationNewsSynthesisRepository()
synthesis_service = RecommendationNewsSynthesisService()
radar_service = RecommendationAthenaRadarService()


class NewsAssessmentRequest(BaseModel):
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


class NewsSynthesisRequest(BaseModel):
    minimumImportance: str = Field(default="low", min_length=1)
    assessments: list[NewsAssessmentRequest] = Field(min_length=1, max_length=200)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _parse_aware_iso(value: object, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} es obligatorio.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
    return _aware_utc(parsed, field)


def _required_dict(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} debe ser un objeto.")
    return value


def _required_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} debe ser una lista.")
    return value


def _radar_from_cycle_record(record: dict[str, Any]) -> AthenaRadarResult:
    package = _required_dict(record.get("package"), "cycle.package")
    radar_payload = _required_dict(package.get("radar"), "cycle.package.radar")
    candidates_payload = _required_list(
        radar_payload.get("candidates"), "cycle.package.radar.candidates"
    )
    if not candidates_payload:
        raise ValueError("El Research Cycle persistido no contiene candidatos Radar.")

    candidates: list[AthenaRadarCandidateInput] = []
    for candidate_index, candidate_raw in enumerate(candidates_payload):
        candidate = _required_dict(
            candidate_raw, f"cycle.package.radar.candidates[{candidate_index}]"
        )
        evidence_payload = _required_list(
            candidate.get("evidence"),
            f"cycle.package.radar.candidates[{candidate_index}].evidence",
        )
        evidence: list[AthenaRadarEvidenceInput] = []
        for evidence_index, item_raw in enumerate(evidence_payload):
            item = _required_dict(
                item_raw,
                f"cycle.package.radar.candidates[{candidate_index}].evidence[{evidence_index}]",
            )
            published_at = item.get("publishedAt")
            evidence.append(
                AthenaRadarEvidenceInput(
                    evidence_id=str(item.get("evidenceId") or ""),
                    category=str(item.get("category") or ""),
                    urgency=str(item.get("urgency") or ""),
                    summary=str(item.get("summary") or ""),
                    available_at=_parse_aware_iso(
                        item.get("availableAt"), "radar.evidence.availableAt"
                    ),
                    source=str(item.get("source") or ""),
                    source_ref=str(item.get("sourceRef") or ""),
                    provider=(
                        str(item.get("provider"))
                        if item.get("provider") is not None
                        else None
                    ),
                    publisher=(
                        str(item.get("publisher"))
                        if item.get("publisher") is not None
                        else None
                    ),
                    published_at=(
                        _parse_aware_iso(published_at, "radar.evidence.publishedAt")
                        if published_at is not None
                        else None
                    ),
                )
            )
        candidates.append(
            AthenaRadarCandidateInput(
                instrument_id=str(candidate.get("instrumentId") or ""),
                symbol=str(candidate.get("symbol") or ""),
                evidence=tuple(evidence),
            )
        )

    rebuilt = radar_service.build(
        as_of=_parse_aware_iso(radar_payload.get("asOf"), "radar.asOf"),
        candidates=tuple(candidates),
    )
    if rebuilt.to_api_dict() != radar_payload:
        raise ValueError(
            "El Radar persistido no coincide con una reconstrucción canónica; síntesis rechazada."
        )
    if str(record.get("radar_hash") or "") != str(
        package.get("cycle", {}).get("integrity", {}).get("radarHash") or ""
    ):
        raise ValueError("El radar_hash persistido no coincide con el Research Cycle.")
    return rebuilt


def _persistence_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "appendOnly": True,
        "packageIntegrityVerified": True,
        "synthesisHash": record["synthesis_hash"],
        "cycleHash": record["cycle_hash"],
        "radarHash": record["radar_hash"],
        "createdAt": record["created_at"],
        "storageClaim": "single_canonical_synthesis_per_cycle_append_only_not_worm_storage",
    }


@router.post("/research-cycle/{cycle_hash}/news-synthesis")
def post_news_synthesis(
    cycle_hash: str,
    request: NewsSynthesisRequest,
) -> dict[str, Any]:
    """Validate external News model output against one persisted PIT research cycle."""

    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        radar = _radar_from_cycle_record(cycle_record)
        result = synthesis_service.build(
            radar_result=radar,
            assessments=tuple(
                NewsModelAssessmentInput(
                    evidence_id=item.evidenceId,
                    model_provider=item.modelProvider,
                    model_name=item.modelName,
                    model_version=item.modelVersion,
                    input_fingerprint=item.inputFingerprint,
                    generated_at=_aware_utc(item.generatedAt, "assessments.generatedAt"),
                    summary=item.summary,
                    importance=item.importance,
                    impact_direction=item.impactDirection,
                    impact_magnitude=item.impactMagnitude,
                    confidence=item.confidence,
                )
                for item in request.assessments
            ),
            minimum_importance=request.minimumImportance,
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
        raise HTTPException(
            status_code=500,
            detail="No se pudo validar y persistir la síntesis News del Research Cycle.",
        ) from exc

    return {
        "data": {
            "cycleBindingVerified": True,
            "cycleHash": cycle_record["cycle_hash"],
            "radarHash": cycle_record["radar_hash"],
            "synthesis": payload,
            "persistence": _persistence_summary(record),
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }
    }


@router.get("/research-cycle/{cycle_hash}/news-synthesis")
def get_news_synthesis(cycle_hash: str) -> dict[str, Any]:
    """Read one synthesis only after both cycle and synthesis integrity checks pass."""

    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        _radar_from_cycle_record(cycle_record)
        record = synthesis_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
        if record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("La síntesis News ya no coincide con el radarHash del ciclo.")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar la síntesis News persistida.",
        ) from exc

    return {
        "data": {
            "cycleBindingVerified": True,
            "cycleHash": cycle_record["cycle_hash"],
            "radarHash": cycle_record["radar_hash"],
            "synthesis": record["package"]["synthesis"],
            "persistence": _persistence_summary(record),
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }
    }
