from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.recommendation_news_synthesis import _radar_from_cycle_record
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-news-synthesis"],
)

cycle_repository = RecommendationProfessionalResearchCycleRepository()
synthesis_repository = RecommendationNewsSynthesisRepository()


@router.get("/news-synthesis/latest")
def get_latest_news_synthesis() -> dict[str, Any]:
    """Return the newest News synthesis only when its current cycle binding still verifies."""
    try:
        record = synthesis_repository.get_latest()
        cycle_record = cycle_repository.get_by_hash(cycle_hash=record["cycle_hash"])
        _radar_from_cycle_record(cycle_record)
        if record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("La síntesis News más reciente ya no coincide con el radarHash canónico.")
        # Re-read by cycle after validating the current cycle so selection order
        # can never substitute for the canonical integrity boundary.
        verified = synthesis_repository.get_by_cycle_hash(cycle_hash=record["cycle_hash"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    synthesis = verified["package"]["synthesis"]
    return {
        "data": {
            "cycleBindingVerified": True,
            "presentationOnly": True,
            "cycleHash": verified["cycle_hash"],
            "radarHash": verified["radar_hash"],
            "synthesis": synthesis,
            "persistence": {
                "appendOnly": True,
                "packageIntegrityVerified": True,
                "synthesisHash": verified["synthesis_hash"],
                "createdAt": verified["created_at"],
            },
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }
    }
