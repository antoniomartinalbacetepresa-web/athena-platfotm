from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.repositories.recommendation_reconciled_portfolio_weight_repository import (
    RecommendationReconciledPortfolioWeightRepository,
)
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_valuation_repository = RecommendationPortfolioValuationEvidenceRepository()
_weight_repository = RecommendationReconciledPortfolioWeightRepository()
_service = RecommendationReconciledPortfolioWeightService()


class ReconciledPortfolioWeightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliationKey: str = Field(min_length=64, max_length=64)
    portfolioValuationEvidenceFingerprint: str = Field(min_length=64, max_length=64)


@router.post("/reconciled-portfolio-weights")
def post_reconciled_portfolio_weights(
    request: ReconciledPortfolioWeightsRequest,
) -> dict[str, object]:
    """Derive and persist diagnostic weights from reconciled state + sealed PIT valuation."""

    try:
        reconciliation = _reconciliation_repository.get_by_key(
            reconciliation_key=request.reconciliationKey,
        )
        valuation = _valuation_repository.get(
            valuation_fingerprint=request.portfolioValuationEvidenceFingerprint,
        )
        if valuation is None:
            raise ValueError("No existe valoración PIT sellada con ese fingerprint.")
        _valuation_repository.validate_record(valuation)
        result = _service.build(
            reconciliation_record=reconciliation,
            valuation_record=valuation,
        )
        _service.validate_artifact(result)
        record = _weight_repository.append(artifact=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron derivar/persistir pesos diagnósticos desde estado reconciliado.",
        ) from exc

    return {
        "data": result,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }


@router.get("/reconciled-portfolio-weights/{weight_evidence_key}")
def get_reconciled_portfolio_weights(weight_evidence_key: str) -> dict[str, object]:
    """Read persisted canonical weight evidence after full tamper verification."""

    try:
        record = _weight_repository.get_by_key(weight_evidence_key=weight_evidence_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Weight evidence persistida carece de artifact válido.")
    return {
        "data": artifact,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }
