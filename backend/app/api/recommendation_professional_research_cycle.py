from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from typing import Annotated, Any
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_account
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
from app.services.recommendation_news_evidence_service import RecommendationNewsEvidenceService
from app.repositories.persisted_market_research_reference_repository import (
    PersistedMarketResearchReferenceRepository, canonical_hash,
)
from app.services.persisted_market_history_service import PersistedMarketHistoryService


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
live_news_evidence_service = RecommendationNewsEvidenceService()
persisted_history_service = PersistedMarketHistoryService()
market_reference_repository = PersistedMarketResearchReferenceRepository()
_PRIVATE_JOURNAL_PREFIX = "__athena_private_owner_"
_MARKET_REFERENCE_PREFIX = "urn:athena:market-history:"


def _reserved_market_reference(value: object) -> bool:
    if not isinstance(value, str):
        return False
    decoded = value
    for _ in range(8):
        normalized = unescape(unquote(decoded))
        if normalized == decoded:
            break
        decoded = normalized
    return decoded.strip().casefold().startswith(_MARKET_REFERENCE_PREFIX)


def _owner_id(account: dict[str, Any]) -> int:
    value = account.get("id")
    if type(value) is not int or value <= 0:
        raise HTTPException(status_code=401, detail="Credenciales no válidas.")
    return value


class CycleRadarEvidenceRequest(BaseModel):
    evidenceId: str = Field(min_length=1)
    category: str = Field(min_length=1)
    urgency: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    provider: str | None = None
    publisher: str | None = None
    publishedAt: datetime | None = None


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


class LiveCompanyResearchCycleRequest(BaseModel):
    """Human-supplied research context; news is retrieved server-side, never client-forged."""

    instrumentId: str = Field(min_length=1)
    companyName: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    journalId: str = Field(min_length=1)
    revisionId: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    journalReferences: list[CycleJournalReferenceRequest] = Field(min_length=1, max_length=200)
    contradictoryEvidence: list[CycleContradictoryEvidenceRequest] = Field(min_length=1, max_length=200)
    priorSnapshotHash: str | None = None
    limit: int = Field(default=8, ge=1, le=25)


class PersistedMarketResearchCycleRequest(BaseModel):
    """Selection and human context only; no client bars, licence flags or hashes."""

    model_config = ConfigDict(extra="forbid")
    instrumentId: int = Field(ge=1, strict=True)
    symbol: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    sourceProvider: str = Field(min_length=1, max_length=128)
    observedFrom: datetime
    observedTo: datetime
    asOf: datetime
    recordedAt: datetime
    journalId: str = Field(min_length=1)
    revisionId: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    journalReferences: list[CycleJournalReferenceRequest] = Field(min_length=1, max_length=199)
    contradictoryEvidence: list[CycleContradictoryEvidenceRequest] = Field(min_length=1, max_length=200)
    priorSnapshotHash: str | None = None
    limit: int = Field(default=200, ge=1, le=200, strict=True)


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
    """Legacy public research endpoint; private journal identifiers are forbidden."""
    if request.journalId.startswith(_PRIVATE_JOURNAL_PREFIX):
        raise HTTPException(status_code=403, detail="Journal privado: escritura pública prohibida.")
    return _persist_professional_research_cycle(request)


def _persist_professional_research_cycle(
    request: ProfessionalResearchCycleRequest, *, owner_id: int | None = None,
    market_reference: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Validate and atomically persist one PIT Radar -> Journal -> Devil's Advocate cycle."""
    try:
        as_of = _aware_utc(request.asOf, "asOf")
        recorded_at = _aware_utc(request.recordedAt, "recordedAt")
        now = datetime.now(timezone.utc)
        if as_of > now or recorded_at > now:
            raise HTTPException(status_code=400, detail="asOf y recordedAt no pueden estar en el futuro.")
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
                            provider=item.provider,
                            publisher=item.publisher,
                            published_at=(
                                _aware_utc(item.publishedAt, "radarEvidence.publishedAt")
                                if item.publishedAt is not None
                                else None
                            ),
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

        reserved_refs = [item.get("sourceRef", "") for item in
                         [*radar_payload["candidates"][0]["evidence"], *journal_payload["references"],
                          *devils_payload["evidence"]]
                         if _reserved_market_reference(item.get("sourceRef"))]
        if market_reference is None and reserved_refs:
            raise ValueError("La referencia de histórico reservada requiere el puente server-side.")

        if market_reference is not None:
            expected_ref = f"urn:athena:market-history:{canonical_hash(market_reference)}"
            radar_refs = radar_payload["candidates"][0]["evidence"]
            journal_refs = journal_payload["references"]
            if (str(market_reference["instrumentId"]) != request.instrumentId
                    or market_reference["symbol"] != request.symbol
                    or _aware_utc(datetime.fromisoformat(market_reference["asOf"]), "reference.asOf") != as_of
                    or len(reserved_refs) != 2 or any(ref != expected_ref for ref in reserved_refs)
                    or sum(item.get("sourceRef") == expected_ref for item in radar_refs) != 1
                    or sum(item.get("sourceRef") == expected_ref for item in journal_refs) != 1):
                raise ValueError("La referencia de histórico no está vinculada al Radar y Journal exactos.")

        cycle_repository.validate_package(
            cycle_payload=payload,
            radar_payload=radar_payload,
            journal_payload=journal_payload,
            devils_advocate_payload=devils_payload,
        )

        # Both append-only artifacts must commit together or not at all.
        # Never accept independently configured SQLite stores for this operation.
        journal_db = journal_repository._database
        cycle_db = cycle_repository._database
        if journal_db.database_path.resolve() != cycle_db.database_path.resolve():
            raise ValueError("Journal y Research Cycle deben compartir la misma base SQLite.")
        if market_reference is not None:
            if (owner_id is None or market_reference_repository._database.database_path.resolve()
                    != cycle_db.database_path.resolve()):
                raise ValueError("La referencia privada y el ciclo deben compartir propietario y SQLite.")
            market_reference_repository.initialize()
        # DDL/executescript must finish before BEGIN IMMEDIATE.
        journal_repository.initialize()
        cycle_repository.initialize()
        with journal_db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if market_reference is not None:
                reference_summary = market_reference_repository.append(
                    market_reference, owner_id=owner_id, connection=connection,
                )
            journal_repository.append(snapshot=journal, connection=connection)
            lineage = journal_repository.verify_lineage(
                journal_id=journal.journal_id, connection=connection,
            )
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
                connection=connection,
                **({"owner_id": owner_id} if owner_id is not None else {}),
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
    if market_reference is not None:
        payload["marketHistoryReference"] = reference_summary
    return {"data": payload}


@router.post("/research-cycle/from-persisted-market-history")
def post_research_cycle_from_persisted_market_history(
    request: PersistedMarketResearchCycleRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, object]:
    """Bind server-selected synthetic history to an owner-bound research cycle.

    Gate DATA remains closed: unverified real origins cannot be persisted by
    this bridge. A fixture reference is not licensed historical/PIT acceptance.
    """
    owner_id = _owner_id(account)
    if request.journalId.startswith(_PRIVATE_JOURNAL_PREFIX):
        raise HTTPException(status_code=400, detail="journalId utiliza un prefijo reservado.")
    if any(_reserved_market_reference(item.sourceRef) for item in
           [*request.journalReferences, *request.contradictoryEvidence]):
        raise HTTPException(status_code=400, detail="Las referencias de histórico se generan exclusivamente en el servidor.")
    try:
        stores = (persisted_history_service, market_reference_repository, journal_repository, cycle_repository)
        if len({store._database.database_path.resolve() for store in stores}) != 1:
            raise ValueError("El histórico y los artefactos de investigación deben compartir SQLite.")
        history = persisted_history_service.get_history(
            instrument_id=request.instrumentId, source_provider=request.sourceProvider,
            observed_from=request.observedFrom, observed_to=request.observedTo,
            as_of=request.asOf, limit=request.limit,
        )
        if history["provenance"].get("evidenceKind") != "synthetic_fixture":
            raise HTTPException(status_code=409, detail="Origen sin derechos acreditados: puente sintético exclusivamente.")
        if not history["data"]:
            raise HTTPException(status_code=409, detail="No hay observaciones elegibles; no se fabricará evidencia.")
        reference = market_reference_repository.build(history)
        if reference["symbol"] != request.symbol.upper():
            raise HTTPException(status_code=400, detail="El símbolo no coincide con el instrumento persistido.")
        digest = canonical_hash(reference)
        source_ref = f"urn:athena:market-history:{digest}"
        available_at = max(datetime.fromisoformat(item["availableAt"]) for item in reference["observations"])
        context = ProfessionalResearchCycleRequest(
            instrumentId=str(request.instrumentId), symbol=reference["symbol"], asOf=request.asOf,
            recordedAt=request.recordedAt,
            journalId=f"{_PRIVATE_JOURNAL_PREFIX}{owner_id}__:{request.journalId}",
            revisionId=request.revisionId, thesis=request.thesis,
            priorSnapshotHash=request.priorSnapshotHash,
            radarEvidence=[CycleRadarEvidenceRequest(
                evidenceId=f"synthetic-market-history:{digest}", category="data_quality", urgency="routine",
                summary=(f"SYNTHETIC FIXTURE: {len(reference['observations'])} local history references; "
                         f"truncated={reference['truncated']}. No real-market, licence, historical PIT or trading claim."),
                availableAt=available_at, source="synthetic_persisted_market_history", sourceRef=source_ref,
            )],
            journalReferences=[*request.journalReferences, CycleJournalReferenceRequest(
                referenceId=f"synthetic-market-history:{digest}", kind="assumption",
                availableAt=available_at, source="synthetic_persisted_market_history", sourceRef=source_ref,
            )],
            contradictoryEvidence=request.contradictoryEvidence,
        )
        return _persist_professional_research_cycle(context, owner_id=owner_id, market_reference=reference)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Instrumento persistido no encontrado.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="No se pudo verificar el histórico para investigación.") from exc


@router.get("/market-history-reference/private/{reference_hash}")
def get_private_market_history_reference(
    reference_hash: str, account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, object]:
    owner_id = _owner_id(account)
    try:
        result = market_reference_repository.get(reference_hash, owner_id=owner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Referencia no encontrada.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="No se pudo verificar la referencia persistida.") from exc
    return {"data": {**result, "readOnly": True, "automaticTrading": False, "productionEligible": False}}



@router.post("/research-cycle/from-live-company-news")
def post_research_cycle_from_live_company_news(
    request: LiveCompanyResearchCycleRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, object]:
    """Fetch current RSS news on the server and atomically persist a human-authored PIT cycle.

    This is NOT historical news replay or issuer/license verification. Human
    thesis, references and contradictory evidence are mandatory; no fabricated
    Journal or Devil's Advocate evidence is generated from headlines.
    """
    # Authenticate before fetching remote news or mutating persistent research.
    # The shared research repository is NOT owner-isolated; do not claim privacy.
    owner_id = _owner_id(account)
    if request.journalId.startswith(_PRIVATE_JOURNAL_PREFIX):
        raise HTTPException(status_code=400, detail="journalId utiliza un prefijo reservado.")
    try:
        news = live_news_evidence_service.build_company_evidence(
            company_name=request.companyName,
            symbol=request.symbol,
            limit=request.limit,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo recuperar evidencia empresarial actual con provenance válida.",
        ) from exc

    evidence = news.get("evidence")
    if (news.get("status") != "news_evidence_ready"
            or not isinstance(evidence, tuple) or not evidence):
        raise HTTPException(
            status_code=409,
            detail="No hay noticias empresariales elegibles para persistir; no se fabricará evidencia.",
        )
    if (news.get("symbol") != request.symbol.strip().upper()
            or news.get("sourceProvider") != "google_news_rss"
            or news.get("productionTruthClaimed") is not False
            or news.get("issuerIdentityIndependentlyVerified") is not False
            or news.get("independentCorroborationClaimed") is not False
            or news.get("automaticTrading") is not False
            or news.get("recommendationInfluence") is not False):
        raise HTTPException(status_code=502, detail="El feed perdió sus límites de procedencia o autoridad.")

    # The PIT cutoff is AFTER the real retrieval, not an invented past timestamp.
    # A caller cannot inject a historical cutoff to relabel live RSS as PIT replay.
    cutoff = datetime.now(timezone.utc)
    try:
        retrieved_at = _aware_utc(
            datetime.fromisoformat(str(news["retrievedAt"]).replace("Z", "+00:00")),
            "retrievedAt",
        )
    except (KeyError, TypeError, ValueError, HTTPException) as exc:
        raise HTTPException(status_code=502, detail="El feed no tiene retrievedAt UTC verificable.") from exc
    # Retrieval is the earliest defensible availability bound for a live RSS
    # observation. A later evidence timestamp would invent knowledge not yet
    # available when the server claims to have fetched the feed.
    if (retrieved_at > cutoff
            or any(
                not isinstance(item, AthenaRadarEvidenceInput)
                or item.available_at.tzinfo is None
                or item.available_at.utcoffset() is None
                or item.available_at > cutoff
                or item.available_at > retrieved_at
                or item.published_at is None
                or item.published_at.tzinfo is None
                or item.published_at.utcoffset() is None
                or item.published_at > item.available_at
                for item in evidence
            )):
        raise HTTPException(status_code=502, detail="El feed contiene evidencia posterior a su recuperación o al reloj real.")

    cycle_request = ProfessionalResearchCycleRequest(
        instrumentId=request.instrumentId,
        symbol=request.symbol.strip().upper(),
        asOf=cutoff,
        radarEvidence=[
            CycleRadarEvidenceRequest(
                evidenceId=item.evidence_id,
                category=item.category,
                urgency=item.urgency,
                summary=item.summary,
                availableAt=item.available_at,
                source=item.source,
                sourceRef=item.source_ref,
                provider=item.provider,
                publisher=item.publisher,
                publishedAt=item.published_at,
            )
            for item in evidence
        ],
        journalId=f"{_PRIVATE_JOURNAL_PREFIX}{owner_id}__:{request.journalId}",
        revisionId=request.revisionId,
        recordedAt=cutoff,
        thesis=request.thesis,
        journalReferences=request.journalReferences,
        priorSnapshotHash=request.priorSnapshotHash,
        contradictoryEvidence=request.contradictoryEvidence,
    )
    result = _persist_professional_research_cycle(cycle_request, owner_id=owner_id)
    result["data"]["liveNewsRetrieval"] = {
        "sourceProvider": "google_news_rss",
        "retrievedAt": retrieved_at.isoformat(),
        "acceptedCount": len(evidence),
        "rejectedCount": news["rejectedCount"],
        "historicalReplay": False,
        "issuerIdentityIndependentlyVerified": False,
        "licenseVerified": False,
        "modelExecutionVerified": False,
        "metadataPersistedInCanonicalCycle": False,
        "evidencePersistedInCanonicalRadar": True,
        "humanReviewRequired": True,
        "authenticatedWrite": True,
        "ownerIsolationVerified": False,
        "cycleOwnerBindingVerified": True,
        "privateReadRequiresAuthentication": True,
        "automaticTrading": False,
    }
    return result


@router.get("/research-cycle/private")
def list_private_professional_research_cycles(
    account: Annotated[dict[str, Any], Depends(current_account)],
    symbol: str | None = Query(default=None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$"),
    limit: int = Query(default=20, ge=1, le=50),
    before_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    """Discover only the authenticated owner's cycles, with no public fallback.

    Metadata is not a license, issuer-verification or model-execution claim.
    Each returned row is canonically revalidated by the repository.
    """
    owner_id = _owner_id(account)
    try:
        records, next_before_id = cycle_repository.list_private(
            owner_id=owner_id, symbol=symbol, limit=limit, before_id=before_id,
        )
    except (ValueError, TypeError) as exc:
        # Invalid stored canonical packages are server integrity failures, not
        # client mistakes. Never echo private payload or database details.
        raise HTTPException(
            status_code=500, detail="No se pudo verificar el índice privado de investigaciones."
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="No se pudo verificar el índice privado de investigaciones."
        ) from exc
    return {
        "data": {
            "items": [
                {
                    "cycleHash": record["cycle_hash"],
                    "symbol": record["symbol"],
                    "instrumentId": record["instrument_id"],
                    "asOf": record["as_of"],
                    "createdAt": record["created_at"],
                    "radarHash": record["radar_hash"],
                    "packageIntegrityVerified": True,
                }
                for record in records
            ],
            "returnedCount": len(records),
            "hasMore": next_before_id is not None,
            "nextBeforeId": next_before_id,
            "readOnly": True,
            "metadataOnly": True,
            "cycleOwnerBindingVerified": True,
            "ownerIsolationVerified": False,
            "licenseVerified": False,
            "issuerIdentityIndependentlyVerified": False,
            "modelExecutionVerified": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "automaticTrading": False,
        }
    }


@router.get("/research-cycle/private/{cycle_hash}")
def get_private_professional_research_cycle(
    cycle_hash: str, account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, object]:
    """Return a private cycle only to its JWT-authenticated owner."""
    return _read_professional_research_cycle(cycle_hash, owner_id=_owner_id(account))


@router.get("/research-cycle/{cycle_hash}")
def get_professional_research_cycle(cycle_hash: str) -> dict[str, object]:
    """Legacy public read; owner-bound cycles fail closed even when the hash is known."""
    return _read_professional_research_cycle(cycle_hash)


def _read_professional_research_cycle(
    cycle_hash: str, *, owner_id: int | None = None,
) -> dict[str, object]:
    try:
        record = cycle_repository.get_by_hash(cycle_hash=cycle_hash, **({"owner_id": owner_id} if owner_id is not None else {}))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar el ciclo profesional persistido.") from exc

    # Canonical hashes protect the reference URI, not the referenced rows.
    # Revalidate private attachments too before reporting the package as intact.
    try:
        package = record["package"]
        refs = [*package["journal"]["references"], *package["devilsAdvocate"]["evidence"],
                *package["radar"]["candidates"][0]["evidence"]]
        for source_ref in {item.get("sourceRef", "") for item in refs}:
            if _reserved_market_reference(source_ref):
                if owner_id is None:
                    raise ValueError("Referencia privada sin propietario.")
                market_reference_repository.get(source_ref[len(_MARKET_REFERENCE_PREFIX):], owner_id=owner_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar la evidencia de histórico del ciclo.") from exc

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
