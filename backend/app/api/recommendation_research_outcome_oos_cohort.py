from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_research_outcome_attribution_repository import (
    RecommendationResearchOutcomeAttributionRepository,
)
from app.repositories.recommendation_research_outcome_oos_cohort_repository import (
    RecommendationResearchOutcomeOosCohortRepository,
)
from app.services.recommendation_research_outcome_oos_cohort_service import (
    OutcomeIssuerIdentityEvidence,
    RecommendationResearchOutcomeOosCohortService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

outcome_repository = RecommendationResearchOutcomeAttributionRepository()
cohort_repository = RecommendationResearchOutcomeOosCohortRepository()
cohort_service = RecommendationResearchOutcomeOosCohortService()


class IssuerIdentityEvidenceRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    issuerId: str | None = None
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    resolutionMethod: str = Field(min_length=1)


class ResearchOutcomeOosCohortRequest(BaseModel):
    cohortId: str = Field(min_length=1)
    asOf: datetime
    outcomeHashes: list[str] = Field(min_length=1, max_length=5000)
    issuerEvidence: list[IssuerIdentityEvidenceRequest] = Field(min_length=1, max_length=5000)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.post("/outcome-oos-cohort")
def post_research_outcome_oos_cohort(
    request: ResearchOutcomeOosCohortRequest,
) -> dict[str, object]:
    """Seal a descriptive issuer-aware OOS cohort from persisted outcome hashes."""
    cutoff = _aware_utc(request.asOf, "asOf")
    identities = tuple(
        OutcomeIssuerIdentityEvidence(
            instrument_id=item.instrumentId,
            issuer_id=item.issuerId,
            available_at=_aware_utc(item.availableAt, "issuerEvidence.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
            resolution_method=item.resolutionMethod,
        )
        for item in request.issuerEvidence
    )

    try:
        # Every lookup re-verifies the stored outcome before the cohort service
        # sees it. Cohort persistence happens only after all rows validate.
        records = [
            outcome_repository.get_by_hash(outcome_hash=outcome_hash)
            for outcome_hash in request.outcomeHashes
        ]
        artifact = cohort_service.build(
            cohort_id=request.cohortId,
            as_of=cutoff,
            outcome_records=records,
            issuer_evidence=identities,
        )
        persisted = cohort_repository.append(artifact=artifact)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir OOS cohort verificable.") from exc

    return {
        "data": {
            **artifact,
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "cohortHash": persisted["cohort_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }


@router.get("/outcome-oos-cohort/{cohort_hash}")
def get_research_outcome_oos_cohort(cohort_hash: str) -> dict[str, object]:
    try:
        record = cohort_repository.get_by_hash(cohort_hash=cohort_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar OOS cohort persistida.") from exc

    return {
        "data": {
            **record["artifact"],
            "persistence": {
                "appendOnly": True,
                "tamperEvident": True,
                "cohortHash": record["cohort_hash"],
                "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
            },
        }
    }
