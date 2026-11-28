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
from app.security.portfolio_artifact_ownership import PortfolioArtifactOwnershipRegistry
from app.security.portfolio_owner_context import current_portfolio_owner_id
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
_ownership = PortfolioArtifactOwnershipRegistry()
_service = RecommendationReconciledPortfolioWeightService()


class ReconciledPortfolioWeightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliationKey: str = Field(min_length=64, max_length=64)
    portfolioValuationEvidenceFingerprint: str = Field(min_length=64, max_length=64)


@router.post("/reconciled-portfolio-weights")
def post_reconciled_portfolio_weights(
    request: ReconciledPortfolioWeightsRequest,
) -> dict[str, object]:
    """Derive owner-scoped diagnostic weights from reconciled state + sealed PIT valuation."""

    try:
        owner_user_id = current_portfolio_owner_id()
        _ownership.require_current_owner(
            artifact_kind="state_reconciliation",
            artifact_key=request.reconciliationKey,
        )
        reconciliation = _reconciliation_repository.get_by_key(
            reconciliation_key=request.reconciliationKey,
        )
        valuation = _valuation_repository.get(
            owner_user_id=owner_user_id,
            valuation_fingerprint=request.portfolioValuationEvidenceFingerprint,
        )
        if valuation is None:
            raise ValueError("No existe valoración PIT sellada para el propietario autenticado con ese fingerprint.")
        _valuation_repository.validate_record(valuation)
        result = _service.build(
            reconciliation_record=reconciliation,
            valuation_record=valuation,
        )
        _service.validate_artifact(result)
        record = _weight_repository.append(artifact=result)
        _ownership.link_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=str(result["weightEvidenceKey"]),
        )
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
    """Read persisted canonical weight evidence only for its authenticated owner."""

    try:
        _ownership.require_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=weight_evidence_key,
        )
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
