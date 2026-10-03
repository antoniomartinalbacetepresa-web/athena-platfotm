from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

service = RecommendationAthenaRadarService()


class AthenaRadarEvidenceRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    category: str = Field(min_length=1)
    urgency: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class AthenaRadarCandidateRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    evidence: list[AthenaRadarEvidenceRequest] = Field(min_length=1, max_length=200)


class AthenaRadarRequest(BaseModel):
    asOf: datetime
    candidates: list[AthenaRadarCandidateRequest] = Field(min_length=1, max_length=500)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("status") != "research_attention_queue_ready":
        raise HTTPException(status_code=500, detail="ATHENA Radar devolvió un estado inválido.")
    if payload.get("mode") != "research_attention_only":
        raise HTTPException(status_code=500, detail="ATHENA Radar perdió el modo research-only.")
    if payload.get("rankingInterpretation") != "research_urgency_not_investment_preference":
        raise HTTPException(status_code=500, detail="ATHENA Radar convirtió prioridad de análisis en preferencia de inversión.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="ATHENA Radar violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="ATHENA Radar intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="ATHENA Radar intentó habilitar ponderación.")

    forbidden_fields = {"score", "expectedReturn", "probability", "buyScore", "sellScore", "targetWeight"}
    if any(field in payload for field in forbidden_fields):
        raise HTTPException(status_code=500, detail="ATHENA Radar expuso scoring, retorno, probabilidad o weighting no calibrado.")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HTTPException(status_code=500, detail="ATHENA Radar perdió la cola de candidatos.")
    count = payload.get("candidateCount")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(candidates):
        raise HTTPException(status_code=500, detail="ATHENA Radar devolvió un recuento incoherente.")

    urgency_order = {"routine": 0, "material": 1, "critical": 2}
    seen_candidates: set[tuple[str, str]] = set()
    seen_evidence_ids: set[str] = set()
    seen_provenance: set[tuple[str, str]] = set()
    previous_sort_key: tuple[int, str, str] | None = None

    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise HTTPException(status_code=500, detail="ATHENA Radar devolvió un candidato inválido.")
        instrument_id = str(candidate.get("instrumentId") or "").strip()
        symbol = str(candidate.get("symbol") or "").strip()
        urgency = str(candidate.get("researchUrgency") or "").strip()
        if not instrument_id or not symbol or urgency not in urgency_order:
            raise HTTPException(status_code=500, detail="ATHENA Radar perdió identidad o urgencia de investigación.")
        identity = (instrument_id.casefold(), symbol.upper())
        if identity in seen_candidates:
            raise HTTPException(status_code=500, detail="ATHENA Radar devolvió candidatos duplicados.")
        seen_candidates.add(identity)

        evidence = candidate.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise HTTPException(status_code=500, detail="ATHENA Radar trató ausencia de evidencia como señal benignа.")
        evidence_count = candidate.get("evidenceCount")
        if not isinstance(evidence_count, int) or isinstance(evidence_count, bool) or evidence_count != len(evidence):
            raise HTTPException(status_code=500, detail="ATHENA Radar devolvió evidencia incoherente.")

        maximum_urgency = "routine"
        for item in evidence:
            if not isinstance(item, dict):
                raise HTTPException(status_code=500, detail="ATHENA Radar devolvió evidencia inválida.")
            required = ("evidenceId", "category", "urgency", "summary", "availableAt", "source", "sourceRef")
            if any(item.get(field) in (None, "") for field in required):
                raise HTTPException(status_code=500, detail="ATHENA Radar perdió provenance PIT.")
            evidence_id = str(item["evidenceId"])
            if evidence_id in seen_evidence_ids:
                raise HTTPException(status_code=500, detail="ATHENA Radar devolvió evidenceId duplicado.")
            seen_evidence_ids.add(evidence_id)
            item_urgency = str(item["urgency"])
            if item_urgency not in urgency_order:
                raise HTTPException(status_code=500, detail="ATHENA Radar devolvió urgencia inválida.")
            if urgency_order[item_urgency] > urgency_order[maximum_urgency]:
                maximum_urgency = item_urgency
            provenance = (str(item["source"]).casefold(), str(item["sourceRef"]).casefold())
            if provenance in seen_provenance:
                raise HTTPException(status_code=500, detail="ATHENA Radar duplicó provenance para elevar urgencia.")
            seen_provenance.add(provenance)
            if any(field in item for field in forbidden_fields):
                raise HTTPException(status_code=500, detail="ATHENA Radar introdujo scoring en evidencia.")

        if maximum_urgency != urgency:
            raise HTTPException(status_code=500, detail="ATHENA Radar devolvió urgencia agregada incoherente.")
        sort_key = (-urgency_order[urgency], instrument_id.casefold(), symbol.upper())
        if previous_sort_key is not None and sort_key < previous_sort_key:
            raise HTTPException(status_code=500, detail="ATHENA Radar devolvió una cola no determinista o mal ordenada.")
        previous_sort_key = sort_key

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="ATHENA Radar devolvió una política inválida.")
    expected = {
        "missingEvidence": "unknown_not_zero_or_benign_and_candidate_requires_explicit_evidence",
        "scoring": "no_numeric_score_without_independent_out_of_sample_calibration",
        "probability": "not_estimated",
        "expectedReturn": "not_estimated",
        "fx": "explicit_evidence_only_no_implicit_fx_neutrality",
        "sourceSecurity": "fmp_and_financialmodelingprep_sources_forbidden",
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            raise HTTPException(status_code=500, detail=f"ATHENA Radar perdió la política {key}.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="ATHENA Radar intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="ATHENA Radar intentó promover producción automáticamente.")


@router.post("/athena-radar")
def post_athena_radar(request: AthenaRadarRequest) -> dict[str, object]:
    """Prioritize PIT research attention without investment ranking, scoring or advice."""

    try:
        result = service.build(
            as_of=_aware_utc(request.asOf, "asOf"),
            candidates=tuple(
                AthenaRadarCandidateInput(
                    instrument_id=candidate.instrumentId,
                    symbol=candidate.symbol,
                    evidence=tuple(
                        AthenaRadarEvidenceInput(
                            evidence_id=item.evidenceId,
                            category=item.category,
                            urgency=item.urgency,
                            summary=item.summary,
                            available_at=_aware_utc(item.availableAt, "evidence.availableAt"),
                            source=item.source,
                            source_ref=item.sourceRef,
                        )
                        for item in candidate.evidence
                    ),
                )
                for candidate in request.candidates
            ),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir ATHENA Radar PIT.") from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="ATHENA Radar devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}
