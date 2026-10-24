from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.google_news_service import GoogleNewsService
from app.services.news_synthesis_service import NewsSynthesisService


router = APIRouter(prefix="/api/v1/news", tags=["news"])
_news_service = GoogleNewsService()
_news_synthesis_service = NewsSynthesisService()


@router.get("/feed")
def get_news_feed(
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=8, ge=1, le=25),
    language: str = Query(default="en", min_length=2, max_length=2),
    country: str = Query(default="US", min_length=2, max_length=2),
) -> dict:
    try:
        result = _news_service.get_feed(
            query=query,
            limit=limit,
            language=language,
            country=country,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener un feed de noticias verificable.",
        ) from exc

    if result.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Contrato de noticias inseguro.")
    if result.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Contrato de noticias inseguro.")
    policy = result.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Contrato de noticias inseguro.")
    if policy.get("athenaRecommendationInfluence") is not False:
        raise HTTPException(status_code=500, detail="Contrato de noticias inseguro.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Contrato de noticias inseguro.")

    try:
        synthesis = _news_synthesis_service.synthesize(result.get("items", ())).to_api_dict()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="El feed de noticias no cumple el contrato de provenance para síntesis.",
        ) from exc

    synthesis_policy = synthesis.get("policy")
    if not isinstance(synthesis_policy, dict):
        raise HTTPException(status_code=500, detail="Contrato de síntesis inseguro.")
    if synthesis_policy.get("automaticAthenaScoreImpact") is not False:
        raise HTTPException(status_code=500, detail="Contrato de síntesis inseguro.")
    if synthesis_policy.get("automaticRecommendationImpact") is not False:
        raise HTTPException(status_code=500, detail="Contrato de síntesis inseguro.")
    if synthesis_policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Contrato de síntesis inseguro.")

    return {**result, "synthesis": synthesis}
