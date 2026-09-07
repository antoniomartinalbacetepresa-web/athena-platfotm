from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

investment_journal_service = RecommendationInvestmentJournalService()


class InvestmentJournalReferenceRequest(BaseModel):
    referenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class InvestmentJournalSnapshotRequest(BaseModel):
    journalId: str = Field(min_length=1)
    revisionId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    recordedAt: datetime
    asOf: datetime
    thesis: str = Field(min_length=1)
    references: list[InvestmentJournalReferenceRequest] = Field(min_length=1, max_length=200)
    priorSnapshotHash: str | None = None


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Investment Journal violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Investment Journal intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Investment Journal intentó habilitar ponderación.")
    snapshot_hash = payload.get("snapshotHash")
    if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
        raise HTTPException(status_code=500, detail="Investment Journal devolvió un fingerprint inválido.")
    references = payload.get("references")
    if not isinstance(references, list) or not references:
        raise HTTPException(status_code=500, detail="Investment Journal devolvió referencias inválidas.")
    seen_ids: set[str] = set()
    required = ("referenceId", "kind", "availableAt", "source", "sourceRef")
    for item in references:
        if not isinstance(item, dict) or any(item.get(field) in (None, "") for field in required):
            raise HTTPException(status_code=500, detail="Investment Journal perdió provenance PIT.")
        reference_id = str(item["referenceId"])
        if reference_id in seen_ids:
            raise HTTPException(status_code=500, detail="Investment Journal devolvió identidades duplicadas.")
        seen_ids.add(reference_id)
        for value in item.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise HTTPException(status_code=500, detail="Investment Journal devolvió datos no finitos.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Investment Journal devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Investment Journal intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Investment Journal intentó promover producción automáticamente.")
    if policy.get("persistentAppendOnlyStorage") is not False:
        raise HTTPException(status_code=500, detail="Investment Journal afirmó persistencia append-only no implementada.")
    if policy.get("immutability") != "snapshot_hash_is_sha256_of_canonical_snapshot_payload":
        raise HTTPException(status_code=500, detail="Investment Journal perdió la garantía de fingerprint canónico.")


@router.post("/investment-journal/snapshot")
def post_investment_journal_snapshot(request: InvestmentJournalSnapshotRequest) -> dict[str, object]:
    """Freeze a PIT research snapshot without claiming durable persistence or advice."""

    references = tuple(
        InvestmentJournalReferenceInput(
            reference_id=item.referenceId,
            kind=item.kind,
            available_at=_aware_utc(item.availableAt, "references.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
        )
        for item in request.references
    )
    try:
        result = investment_journal_service.freeze_snapshot(
            journal_id=request.journalId,
            revision_id=request.revisionId,
            symbol=request.symbol,
            recorded_at=_aware_utc(request.recordedAt, "recordedAt"),
            as_of=_aware_utc(request.asOf, "asOf"),
            thesis=request.thesis,
            references=references,
            prior_snapshot_hash=request.priorSnapshotHash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo congelar el Investment Journal PIT de ATHENA.") from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Investment Journal devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}
