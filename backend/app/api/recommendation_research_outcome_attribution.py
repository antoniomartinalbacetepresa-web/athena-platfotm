from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.repositories.recommendation_research_outcome_attribution_repository import (
    RecommendationResearchOutcomeAttributionRepository,
)
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)
from app.services.recommendation_research_outcome_attribution_service import (
    RecommendationResearchOutcomeAttributionService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

cycle_repository = RecommendationProfessionalResearchCycleRepository()
outcome_repository = RecommendationResearchOutcomeAttributionRepository()
attribution_service = RecommendationPerformanceAttributionService()
outcome_service = RecommendationResearchOutcomeAttributionService()


class EvidenceRequest(BaseModel):
    value: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class FactorContributionRequest(BaseModel):
    factor: str = Field(min_length=1)
    contribution: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class ResearchOutcomeAttributionRequest(BaseModel):
    outcomeId: str = Field(min_length=1)
    instrumentId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    instrumentCurrency: str = Field(min_length=3, max_length=3)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    fxPair: str = Field(min_length=7, max_length=7)
    benchmarkId: str = Field(min_length=1)
    asOf: datetime
    periodStart: datetime
    periodEnd: datetime
    totalReturn: EvidenceRequest
    marketContribution: EvidenceRequest
    fxContribution: EvidenceRequest
    factorContributions: list[FactorContributionRequest] = Field(default_factory=list, max_length=20)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.post("/research-cycle/{cycle_hash}/outcome-attribution")
def post_research_outcome_attribution(
    cycle_hash: str,
    request: ResearchOutcomeAttributionRequest,
) -> dict[str, object]:
    """Persist a posterior PIT attribution bound to an immutable research cycle."""
    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")

    def evidence(item: EvidenceRequest, field: str) -> AttributionEvidence:
        return AttributionEvidence(
            value=item.value,
            available_at=_aware_utc(item.availableAt, f"{field}.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
        )

    factors = tuple(
        FactorContributionEvidence(
            factor=item.factor,
            contribution=item.contribution,
            available_at=_aware_utc(item.availableAt, "factorContributions.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
        )
        for item in request.factorContributions
    )

    try:
        cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
        attribution = attribution_service.evaluate(
            as_of=as_of,
            item=RecommendationPerformanceAttributionInput(
                instrument_id=request.instrumentId,
                symbol=request.symbol,
                instrument_currency=request.instrumentCurrency,
                reporting_currency=request.reportingCurrency,
                fx_pair=request.fxPair,
                benchmark_id=request.benchmarkId,
                period_start=period_start,
                period_end=period_end,
                total_return=evidence(request.totalReturn, "totalReturn"),
                market_contribution=evidence(request.marketContribution, "marketContribution"),
                fx_contribution=evidence(request.fxContribution, "fxContribution"),
                factor_contributions=factors,
            ),
        ).to_api_dict()
        outcome = outcome_service.bind(
            outcome_id=request.outcomeId,
            cycle_record=cycle_record,
            attribution_payload=attribution,
        )
        persisted = outcome_repository.append(payload=outcome)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo persistir el outcome attribution PIT.") from exc

    return {
        "data": {
            **outcome,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "outcomeHash": persisted["outcome_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }


@router.get("/research-cycle/outcome-attribution/{outcome_hash}")
def get_research_outcome_attribution(outcome_hash: str) -> dict[str, object]:
    try:
        record = outcome_repository.get_by_hash(outcome_hash=outcome_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar outcome attribution persistido.") from exc

    payload = record["payload"]
    return {
        "data": {
            **payload,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "outcomeHash": record["outcome_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }
