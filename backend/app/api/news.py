from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.google_news_service import GoogleNewsService
from app.services.recommendation_news_evidence_service import RecommendationNewsEvidenceService
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


@router.get("/company-evidence")
def get_company_news_radar_evidence(
    companyName: str = Query(min_length=1, max_length=100),
    symbol: str = Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9.\\-]*$"),
    limit: int = Query(default=8, ge=1, le=25),
    asOf: datetime | None = Query(default=None),
) -> dict:
    """Read-only company news -> structured PIT Radar evidence, never a signal.

    Live Google RSS retrieval is not historical PIT replay, issuer verification,
    independent corroboration, licensed redistribution or model execution.
    """
    if asOf is not None:
        if asOf.tzinfo is None or asOf.utcoffset() is None:
            raise HTTPException(status_code=400, detail="asOf debe incluir zona horaria.")
        if asOf.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="asOf no puede estar en el futuro.")
    try:
        result = RecommendationNewsEvidenceService(
            news_service=_news_service,
        ).build_company_evidence(
            company_name=companyName, symbol=symbol, limit=limit, as_of=asOf,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener evidencia de noticias con provenance válida.",
        ) from exc

    evidence = [
        {
            "evidenceId": item.evidence_id,
            "category": item.category,
            "urgency": item.urgency,
            "summary": item.summary,
            "availableAt": item.available_at.isoformat(),
            "source": item.source,
            "sourceRef": item.source_ref,
            "provider": item.provider,
            "publisher": item.publisher,
            "publishedAt": item.published_at.isoformat() if item.published_at else None,
        }
        for item in result["evidence"]
    ]
    return {"data": {
        **{key: value for key, value in result.items() if key != "evidence"},
        "companyName": companyName.strip(),
        "mode": "research_evidence_only",
        "advisoryStatus": "no_advice",
        "readOnly": True,
        "productionEligible": False,
        "licenseVerified": False,
        "modelExecutionVerified": False,
        "persisted": False,
        "evidence": evidence,
    }}
