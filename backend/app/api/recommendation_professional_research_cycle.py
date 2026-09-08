from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput,
    RecommendationDevilsAdvocateService,
)
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)
from app.services.recommendation_professional_research_cycle_service import (
    RecommendationProfessionalResearchCycleService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

radar_service = RecommendationAthenaRadarService()
journal_service = RecommendationInvestmentJournalService()
journal_repository = RecommendationInvestmentJournalRepository()
devils_advocate_service = RecommendationDevilsAdvocateService()
cycle_service = RecommendationProfessionalResearchCycleService()
cycle_repository = RecommendationProfessionalResearchCycleRepository()


class CycleRadarEvidenceRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    category: str = Field(min_length=1)
    urgency: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class CycleJournalReferenceRequest(BaseModel):
    referenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class CycleContradictoryEvidenceRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    strength: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class ProfessionalResearchCycleRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    asOf: datetime
    radarEvidence: list[CycleRadarEvidenceRequest] = Field(min_length=1, max_length=200)
    journalId: str = Field(min_length=1)
    revisionId: str = Field(min_length=1)
    recordedAt: datetime
    thesis: str = Field(min_length=1)
    journalReferences: list[CycleJournalReferenceRequest] = Field(min_length=1, max_length=200)
    priorSnapshotHash: str | None = None
    contradictoryEvidence: list[CycleContradictoryEvidenceRequest] = Field(min_length=1, max_length=200)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_cycle_contract(payload: dict[str, object]) -> None:
    if payload.get("status") != "professional_research_cycle_ready_for_human_review":
        raise HTTPException(status_code=500, detail="El ciclo profesional devolvió un estado inválido.")
    if payload.get("mode") != "research_only":
        raise HTTPException(status_code=500, detail="El ciclo profesional dejó de ser research-only.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="El ciclo profesional violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="El ciclo profesional intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="El ciclo profesional intentó habilitar ponderación.")
    if payload.get("humanReviewRequired") is not True:
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió la revisión humana obligatoria.")
    if payload.get("researchUrgencyInterpretation") != "attention_priority_not_investment_preference":
        raise HTTPException(status_code=500, detail="El ciclo profesional convirtió urgencia en preferencia de inversión.")
    if payload.get("fxEvidenceStatus") not in {"explicit", "unknown_not_neutral"}:
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió el estado FX explícito/unknown.")

    forbidden = {"score", "expectedReturn", "probability", "buyScore", "sellScore", "targetWeight"}
    if any(field in payload for field in forbidden):
        raise HTTPException(status_code=500, detail="El ciclo profesional expuso scoring o weighting no calibrado.")

    journal = payload.get("journal")
    if not isinstance(journal, dict) or journal.get("snapshotBindingVerified") is not True:
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió el binding al snapshot del Journal.")
    if not journal.get("snapshotHash"):
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió el fingerprint del Journal.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió su política de seguridad.")
    if policy.get("fx") != "explicit_or_unknown_never_implicitly_neutral":
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió la política FX.")
    if policy.get("sourceSecurity") != "fmp_and_financialmodelingprep_sources_forbidden_across_cycle":
        raise HTTPException(status_code=500, detail="El ciclo profesional perdió el bloqueo de FMP.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="El ciclo profesional intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="El ciclo profesional intentó promover producción automáticamente.")


def _assert_lineage(lineage: dict[str, object], *, snapshot_hash: str, journal_id: str, symbol: str) -> None:
    if lineage.get("status") != "lineage_verified":
        raise HTTPException(status_code=500, detail="Investment Journal no verificó el lineage persistido.")
    if lineage.get("journalId") != journal_id or str(lineage.get("symbol") or "").upper() != symbol.upper():
        raise HTTPException(status_code=500, detail="El lineage persistido no coincide con la identidad del ciclo.")
    if lineage.get("headSnapshotHash") != snapshot_hash:
        raise HTTPException(status_code=500, detail="El snapshot del ciclo no es el head persistido del Journal.")
    if lineage.get("advisoryStatus") != "no_advice" or lineage.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="El lineage persistido perdió el contrato research-only.")
    if lineage.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="El lineage persistido intentó habilitar ponderación.")
    policy = lineage.get("policy")
    if not isinstance(policy, dict) or policy.get("appendOnly") is not True:
        raise HTTPException(status_code=500, detail="El lineage persistido perdió la garantía append-only del repositorio.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="El lineage persistido intentó habilitar automatización productiva.")


def _persistence_summary(record: dict[str, object]) -> dict[str, object]:
    return {
        "appendOnly": True,
        "packageIntegrityVerified": True,
        "cycleHash": record["cycle_hash"],
        "createdAt": record["created_at"],
        "storageClaim": "tamper_evident_append_only_repository_not_worm_storage",
    }


@router.post("/research-cycle")
def post_professional_research_cycle(request: ProfessionalResearchCycleRequest) -> dict[str, object]:
    """Validate, then persist, one PIT Radar -> Journal -> Devil's Advocate research cycle."""

    try:
        as_of = _aware_utc(request.asOf, "asOf")
        recorded_at = _aware_utc(request.recordedAt, "recordedAt")
        radar = radar_service.build(
            as_of=as_of,
            candidates=(
                AthenaRadarCandidateInput(
                    instrument_id=request.instrumentId,
                    symbol=request.symbol,
                    evidence=tuple(
                        AthenaRadarEvidenceInput(
                            evidence_id=item.evidenceId,
                            category=item.category,
                            urgency=item.urgency,
                            summary=item.summary,
                            available_at=_aware_utc(item.availableAt, "radarEvidence.availableAt"),
                            source=item.source,
                            source_ref=item.sourceRef,
                        )
                        for item in request.radarEvidence
                    ),
                ),
            ),
        )
        journal = journal_service.freeze_snapshot(
            journal_id=request.journalId,
            revision_id=request.revisionId,
            symbol=request.symbol,
            recorded_at=recorded_at,
            as_of=as_of,
            thesis=request.thesis,
            references=tuple(
                InvestmentJournalReferenceInput(
                    reference_id=item.referenceId,
                    kind=item.kind,
                    available_at=_aware_utc(item.availableAt, "journalReferences.availableAt"),
                    source=item.source,
                    source_ref=item.sourceRef,
                )
                for item in request.journalReferences
            ),
            prior_snapshot_hash=request.priorSnapshotHash,
        )
        devils_advocate = devils_advocate_service.review(
            journal_id=journal.journal_id,
            revision_id=journal.revision_id,
            snapshot_hash=journal.snapshot_hash,
            symbol=request.symbol,
            as_of=as_of,
            evidence=tuple(
                DevilsAdvocateEvidenceInput(
                    evidence_id=item.evidenceId,
                    kind=item.kind,
                    claim=item.claim,
                    strength=item.strength,
                    available_at=_aware_utc(item.availableAt, "contradictoryEvidence.availableAt"),
                    source=item.source,
                    source_ref=item.sourceRef,
                )
                for item in request.contradictoryEvidence
            ),
        )
        result = cycle_service.bind(
            instrument_id=request.instrumentId,
            radar=radar,
            journal=journal,
            devils_advocate=devils_advocate,
        )
        payload = result.to_api_dict()
        _assert_cycle_contract(payload)

        radar_payload = radar.to_api_dict()
        journal_payload = journal.to_api_dict()
        devils_payload = devils_advocate.to_api_dict()

        # Validate the entire durable package before the first persistent side
        # effect. Invalid PIT, identity, provenance, FMP, advice, weighting,
        # hashes or trading contracts cannot leave a partial cycle record.
        cycle_repository.validate_package(
            cycle_payload=payload,
            radar_payload=radar_payload,
            journal_payload=journal_payload,
            devils_advocate_payload=devils_payload,
        )

        journal_repository.append(snapshot=journal)
        lineage = journal_repository.verify_lineage(journal_id=journal.journal_id)
        _assert_lineage(
            lineage,
            snapshot_hash=journal.snapshot_hash,
            journal_id=journal.journal_id,
            symbol=journal.symbol,
        )
        cycle_record = cycle_repository.append(
            cycle_payload=payload,
            radar_payload=radar_payload,
            journal_payload=journal_payload,
            devils_advocate_payload=devils_payload,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir el ciclo profesional PIT.") from exc

    payload["journalPersistence"] = {
        "appendOnly": True,
        "lineageVerified": True,
        "headSnapshotHash": journal.snapshot_hash,
    }
    payload["cyclePersistence"] = _persistence_summary(cycle_record)
    return {"data": payload}


@router.get("/research-cycle/{cycle_hash}")
def get_professional_research_cycle(cycle_hash: str) -> dict[str, object]:
    """Return one persisted cycle only after full package-integrity verification."""

    try:
        record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar el ciclo profesional persistido.") from exc

    return {
        "data": {
            "package": record["package"],
            "persistence": _persistence_summary(record),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "automaticTrading": False,
        }
    }
