from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
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
_service = RecommendationReconciledPortfolioWeightService()


class ReconciledPortfolioWeightsRequest(BaseModel):
    reconciliationKey: str = Field(min_length=64, max_length=64)
    portfolioValuationEvidenceFingerprint: str = Field(min_length=64, max_length=64)


@router.post("/reconciled-portfolio-weights")
def post_reconciled_portfolio_weights(
    request: ReconciledPortfolioWeightsRequest,
) -> dict[str, object]:
    """Derive diagnostic weights only from persisted reconciled state and sealed PIT valuation."""

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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron derivar pesos diagnósticos desde estado reconciliado.",
        ) from exc

    return {"data": result}
