"""Owner-private review of a server-generated artificial strategy artifact."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_account
from app.api import rebound25_artifacts as artifact_api
from app.api import recommendation_professional_research_cycle as cycles

router = APIRouter(prefix="/api/v1/research/strategies/rebound25/artifacts",
                   tags=["synthetic-artifact-private-research"])


class ArtifactResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journalId: str = Field(min_length=1, max_length=160)
    revisionId: str = Field(min_length=1, max_length=160)
    recordedAt: datetime
    asOf: datetime
    thesis: str = Field(min_length=1, max_length=4000)
    journalReferences: list[cycles.CycleJournalReferenceRequest] = Field(min_length=1, max_length=199)
    contradictoryEvidence: list[cycles.CycleContradictoryEvidenceRequest] = Field(min_length=1, max_length=200)
    priorSnapshotHash: str | None = None


@router.post("/{artifact_hash}/research-cycle")
def review_artifact(artifact_hash: str, request: ArtifactResearchRequest,
                    account: Annotated[dict, Depends(current_account)]) -> dict:
    owner = cycles._owner_id(account)
    if request.journalId.startswith(cycles._PRIVATE_JOURNAL_PREFIX):
        raise HTTPException(status_code=400, detail="Identificador Journal reservado.")
    prefixes = (cycles._BACKTEST_REFERENCE_PREFIX, cycles._MARKET_REFERENCE_PREFIX, cycles._SOURCE_CYCLE_PREFIX)
    if any(cycles._reserved_reference(item.sourceRef, prefix) for prefix in prefixes
           for item in [*request.journalReferences, *request.contradictoryEvidence]):
        raise HTTPException(status_code=400, detail="Las referencias reservadas se resuelven en el servidor.")
    try:
        artifact = artifact_api.artifact_service.get(owner_id=owner, artifact_hash=artifact_hash)
        available = cycles._aware_utc(datetime.fromisoformat(artifact["createdAt"]), "artifact.createdAt")
        recorded = cycles._aware_utc(request.recordedAt, "recordedAt")
        cutoff = cycles._aware_utc(request.asOf, "asOf")
        if not available <= recorded <= cutoff <= datetime.now(timezone.utc):
            raise ValueError("El cálculo no estaba disponible en ese corte de investigación.")
        source_ref = f"{cycles._BACKTEST_REFERENCE_PREFIX}{artifact_hash}"
        context = cycles.ProfessionalResearchCycleRequest(
            instrumentId=artifact["result"]["instrumentId"], symbol="SYNTH",
            journalId=f"{cycles._PRIVATE_JOURNAL_PREFIX}{owner}__:{request.journalId}",
            revisionId=request.revisionId, recordedAt=recorded, asOf=cutoff,
            thesis=request.thesis, priorSnapshotHash=request.priorSnapshotHash,
            radarEvidence=[cycles.CycleRadarEvidenceRequest(
                evidenceId=f"synthetic-backtest:{artifact_hash}", category="data_quality", urgency="routine",
                summary=(f"SERVER-GENERATED SYNTHETIC BACKTEST: {artifact['result']['closedTradeCount']} hypothetical closed trades; "
                         "not licensed market evidence, OOS validation or investment performance."),
                availableAt=available, source="server_generated_synthetic_backtest", sourceRef=source_ref,
            )],
            journalReferences=[*request.journalReferences, cycles.CycleJournalReferenceRequest(
                referenceId=f"synthetic-backtest:{artifact_hash}", kind="assumption", availableAt=available,
                source="server_generated_synthetic_backtest", sourceRef=source_ref,
            )], contradictoryEvidence=request.contradictoryEvidence,
        )
        response = cycles._persist_professional_research_cycle(context, owner_id=owner, synthetic_backtest=artifact)
        response["data"]["syntheticBacktestReference"] = {
            "artifactHash": artifact_hash, "sourceRef": source_ref, "availableAt": available.isoformat(),
            "seriesAsOf": artifact["result"]["asOf"], "resultFingerprint": artifact["result"]["resultFingerprint"],
            "serverFixtureGenerated": True, "listingIdentityVerified": False,
            "productionEligible": False, "automaticTrading": False,
        }
        return response
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Artefacto privado no encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Referencia o contexto de investigación no verificable.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="No se pudo persistir la revisión privada del backtest.") from exc
