from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput,
    RecommendationDevilsAdvocateService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

service = RecommendationDevilsAdvocateService()


class DevilsAdvocateEvidenceRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    strength: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class DevilsAdvocateRequest(BaseModel):
    journalId: str = Field(min_length=1)
    revisionId: str = Field(min_length=1)
    snapshotHash: str = Field(min_length=64, max_length=64)
    symbol: str = Field(min_length=1)
    asOf: datetime
    evidence: list[DevilsAdvocateEvidenceRequest] = Field(min_length=1, max_length=200)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("status") != "contradictory_evidence_review_ready":
        raise HTTPException(status_code=500, detail="Devil's Advocate devolvió un estado inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Devil's Advocate violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Devil's Advocate intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Devil's Advocate intentó habilitar ponderación.")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise HTTPException(status_code=500, detail="Devil's Advocate perdió la evidencia contradictoria.")
    count = payload.get("evidenceCount")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(evidence):
        raise HTTPException(status_code=500, detail="Devil's Advocate devolvió un recuento incoherente.")
    seen_ids: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail="Devil's Advocate devolvió evidencia inválida.")
        required = ("evidenceId", "kind", "claim", "strength", "availableAt", "source", "sourceRef")
        if any(item.get(field) in (None, "") for field in required):
            raise HTTPException(status_code=500, detail="Devil's Advocate perdió provenance PIT.")
        evidence_id = str(item["evidenceId"])
        if evidence_id in seen_ids:
            raise HTTPException(status_code=500, detail="Devil's Advocate devolvió identidades duplicadas.")
        seen_ids.add(evidence_id)
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Devil's Advocate devolvió una política inválida.")
    expected = {
        "fabrication": "only_explicit_caller_supplied_evidence_is_reviewed_no_objections_are_invented",
        "scoring": "no_numeric_score_or_probability_without_independent_calibration",
        "journalBinding": "review_is_bound_to_explicit_journal_revision_and_snapshot_hash",
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            raise HTTPException(status_code=500, detail=f"Devil's Advocate perdió la política {key}.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Devil's Advocate intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Devil's Advocate intentó promover producción automáticamente.")


@router.post("/devils-advocate")
def post_devils_advocate(request: DevilsAdvocateRequest) -> dict[str, object]:
    """Review explicit PIT contradictory evidence without inventing objections or advice."""

    try:
        result = service.review(
            journal_id=request.journalId,
            revision_id=request.revisionId,
            snapshot_hash=request.snapshotHash,
            symbol=request.symbol,
            as_of=_aware_utc(request.asOf, "asOf"),
            evidence=tuple(
                DevilsAdvocateEvidenceInput(
                    evidence_id=item.evidenceId,
                    kind=item.kind,
                    claim=item.claim,
                    strength=item.strength,
                    available_at=_aware_utc(item.availableAt, "evidence.availableAt"),
                    source=item.source,
                    source_ref=item.sourceRef,
                )
                for item in request.evidence
            ),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo ejecutar Devil's Advocate PIT de ATHENA.") from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Devil's Advocate devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}
