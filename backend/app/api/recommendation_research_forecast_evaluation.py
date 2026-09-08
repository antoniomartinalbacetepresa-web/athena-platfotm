from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.repositories.recommendation_research_evaluation_specification_repository import (
    RecommendationResearchEvaluationSpecificationRepository,
)
from app.repositories.recommendation_research_forecast_error_oos_summary_repository import (
    RecommendationResearchForecastErrorOosSummaryRepository,
)
from app.repositories.recommendation_research_forecast_error_repository import (
    RecommendationResearchForecastErrorRepository,
)
from app.repositories.recommendation_research_outcome_attribution_repository import (
    RecommendationResearchOutcomeAttributionRepository,
)
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from app.services.recommendation_research_forecast_error_oos_summary_service import (
    RecommendationResearchForecastErrorOosSummaryService,
)
from app.services.recommendation_research_forecast_error_service import (
    RecommendationResearchForecastErrorService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

cycle_repository = RecommendationProfessionalResearchCycleRepository()
specification_repository = RecommendationResearchEvaluationSpecificationRepository()
outcome_repository = RecommendationResearchOutcomeAttributionRepository()
error_repository = RecommendationResearchForecastErrorRepository()
oos_summary_repository = RecommendationResearchForecastErrorOosSummaryRepository()
specification_service = RecommendationResearchEvaluationSpecificationService()
error_service = RecommendationResearchForecastErrorService()
oos_summary_service = RecommendationResearchForecastErrorOosSummaryService()


class EvaluationSpecificationRequest(BaseModel):
    specificationId: str = Field(min_length=1)
    horizonSeconds: int = Field(gt=0)
    expectedTotalReturn: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    method: str = Field(min_length=1)


class ForecastErrorRequest(BaseModel):
    specificationHash: str = Field(min_length=64, max_length=64)
    outcomeHash: str = Field(min_length=64, max_length=64)


class ForecastErrorOosSummaryRequest(BaseModel):
    summaryId: str = Field(min_length=1, max_length=200)
    asOf: datetime
    errorHashes: list[str] = Field(min_length=1, max_length=5000)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.post("/research-cycle/{cycle_hash}/evaluation-specification")
def post_evaluation_specification(
    cycle_hash: str,
    request: EvaluationSpecificationRequest,
) -> dict[str, object]:
    """Freeze one measurable ex-ante total-return target before posterior outcomes."""
    available_at = _aware_utc(request.availableAt, "availableAt")
    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        artifact = specification_service.build(
            specification_id=request.specificationId,
            cycle_record=cycle_record,
            horizon_seconds=request.horizonSeconds,
            expected_total_return=request.expectedTotalReturn,
            available_at=available_at,
            source=request.source,
            source_ref=request.sourceRef,
            method=request.method,
        )
        persisted = specification_repository.append(artifact=artifact)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo sellar evaluation specification ex-ante.") from exc

    return {
        "data": {
            **artifact,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "specificationHash": persisted["specification_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }


@router.get("/evaluation-specification/{specification_hash}")
def get_evaluation_specification(specification_hash: str) -> dict[str, object]:
    try:
        record = specification_repository.get_by_hash(specification_hash=specification_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar evaluation specification.") from exc
    return {"data": record["artifact"]}


@router.post("/forecast-error")
def post_forecast_error(request: ForecastErrorRequest) -> dict[str, object]:
    """Compare an immutable ex-ante specification with an immutable posterior outcome."""
    try:
        specification_record = specification_repository.get_by_hash(
            specification_hash=request.specificationHash
        )
        outcome_record = outcome_repository.get_by_hash(outcome_hash=request.outcomeHash)
        artifact = error_service.evaluate(
            specification_record=specification_record,
            outcome_record=outcome_record,
        )
        persisted = error_repository.append(artifact=artifact)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo medir forecast error verificable.") from exc

    return {
        "data": {
            **artifact,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "errorHash": persisted["error_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }


@router.get("/forecast-error/{error_hash}")
def get_forecast_error(error_hash: str) -> dict[str, object]:
    try:
        record = error_repository.get_by_hash(error_hash=error_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar forecast error persistido.") from exc
    return {"data": record["artifact"]}


@router.post("/forecast-error-oos-summary")
def post_forecast_error_oos_summary(
    request: ForecastErrorOosSummaryRequest,
) -> dict[str, object]:
    """Aggregate only persisted forecast errors into a descriptive PIT OOS summary."""

    as_of = _aware_utc(request.asOf, "asOf")
    try:
        if len(set(request.errorHashes)) != len(request.errorHashes):
            raise ValueError("errorHashes contiene duplicados.")
        error_records = [
            error_repository.get_by_hash(error_hash=error_hash)
            for error_hash in request.errorHashes
        ]
        specification_records = []
        for record in error_records:
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("Forecast error persistido carece de artifact válido.")
            specification_hash = artifact.get("specificationHash")
            if not isinstance(specification_hash, str):
                raise ValueError("Forecast error persistido perdió specificationHash.")
            specification_records.append(
                specification_repository.get_by_hash(specification_hash=specification_hash)
            )
        artifact = oos_summary_service.build(
            summary_id=request.summaryId,
            as_of=as_of,
            error_records=error_records,
            specification_records=specification_records,
        )
        persisted = oos_summary_repository.append(artifact=artifact)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir OOS forecast error summary verificable.",
        ) from exc

    return {
        "data": {
            **artifact,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "semanticIntegrityVerified": True,
                "summaryHash": persisted["summary_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }


@router.get("/forecast-error-oos-summary/{summary_hash}")
def get_forecast_error_oos_summary(summary_hash: str) -> dict[str, object]:
    try:
        record = oos_summary_repository.get_by_hash(summary_hash=summary_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar OOS forecast error summary persistido.",
        ) from exc
    return {"data": record["artifact"]}
