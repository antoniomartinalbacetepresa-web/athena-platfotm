from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.recommendation_athena_synthesis import (
    _dependencies,
    _input_contract,
    _response_provenance,
)
from app.repositories.recommendation_latest_athena_synthesis_repository import (
    RecommendationLatestAthenaSynthesisRepository,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-athena-synthesis"],
)
latest_repository = RecommendationLatestAthenaSynthesisRepository()


@router.get("/athena-synthesis/latest")
def get_latest_athena_synthesis() -> dict:
    """Return the latest synthesis only when it still matches canonical inputs.

    Latest selection is presentation-only. The endpoint re-resolves the selected
    Research Cycle and all required category syntheses, then recomputes the
    canonical input fingerprint before exposing the artifact. A stale or
    tampered latest record therefore fails closed instead of being presented.
    """

    try:
        record = latest_repository.get_latest()
        cycle_hash = record["cycle_hash"]
        cycle, news, investors, contract = _dependencies(cycle_hash)
        input_contract = _input_contract(cycle, news, investors, contract)
        stored = record["package"]["synthesis"]

        expected_news = news["synthesis_hash"] if news else None
        expected_investors = investors["synthesis_hash"] if investors else None
        if record["radar_hash"] != cycle["radar_hash"]:
            raise ValueError("La última ATHENA synthesis no coincide con el Radar canónico actual.")
        if record["news_synthesis_hash"] != expected_news:
            raise ValueError("La última ATHENA synthesis no coincide con News canónica actual.")
        if stored.get("investorsSynthesisHash") != expected_investors and not (
            expected_investors is None and "investorsSynthesisHash" not in stored
        ):
            raise ValueError("La última ATHENA synthesis no coincide con Investors canónica actual.")
        if stored.get("inputFingerprint") != input_contract["inputFingerprint"]:
            raise ValueError("La última ATHENA synthesis está obsoleta respecto al input canónico actual.")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "data": {
            "artifactBindingVerified": True,
            "cycleHash": cycle_hash,
            "synthesis": stored,
            "provenance": _response_provenance(
                input_contract,
                input_contract["inputFingerprint"],
            ),
            "selection": {
                "policy": "latest_persisted_then_canonical_revalidation",
                "presentationOnly": True,
                "recommendationInfluence": False,
                "automaticTrading": False,
            },
        }
    }
