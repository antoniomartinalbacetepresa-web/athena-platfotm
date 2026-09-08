from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
)
from app.services.recommendation_portfolio_state_reconciliation_service import (
    PortfolioSnapshotEvidence,
    PortfolioSnapshotPositionEvidence,
    PortfolioStateReconciliationInput,
    RecommendationPortfolioStateReconciliationService,
)
from app.services.recommendation_portfolio_state_reconstruction_service import (
    OpeningCashEvidence,
    OpeningPositionEvidence,
    RecommendationPortfolioStateReconstructionInput,
    RecommendationPortfolioStateReconstructionService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_DEFAULT_LEDGER_PATH = "var/athena/portfolio_event_ledger.jsonl"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()


class OpeningCashRequest(BaseModel):
    balance: float
    currency: str = Field(min_length=3, max_length=3)
    observedAt: datetime
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class OpeningPositionRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    quantity: float
    observedAt: datetime
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class PortfolioStateReconstructionRequest(BaseModel):
    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    reconstructionStart: datetime
    openingCash: OpeningCashRequest
    openingPositions: list[OpeningPositionRequest] = Field(default_factory=list)
    asOf: datetime


class PortfolioStateSnapshotPositionRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    quantity: float


class PortfolioStateSnapshotRequest(BaseModel):
    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    cashBalance: float
    positions: list[PortfolioStateSnapshotPositionRequest] = Field(default_factory=list)
    observedAt: datetime
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class PortfolioStateReconciliationRequest(BaseModel):
    reconstructedState: dict[str, object]
    snapshot: PortfolioStateSnapshotRequest
    asOf: datetime


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _service() -> RecommendationPortfolioStateReconstructionService:
    configured = os.environ.get(
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH",
        _DEFAULT_LEDGER_PATH,
    ).strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Portfolio event ledger no tiene ruta de persistencia configurada.",
        )
    ledger = RecommendationPortfolioEventLedgerService(Path(configured))
    return RecommendationPortfolioStateReconstructionService(ledger)


def _assert_reconciliation_contract(payload: dict[str, object]) -> None:
    if _SHA256_RE.fullmatch(str(payload.get("reconciliationKey", ""))) is None:
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconciliation devolvió identidad inválida.",
        )
    if (
        payload.get("advisoryStatus") != "no_advice"
        or payload.get("productionEligible") is not False
        or payload.get("isWeightingReady") is not False
    ):
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconciliation violó los límites de seguridad.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconciliation intentó habilitar trading.",
        )
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconciliation intentó promoción automática.",
        )


@router.post("/portfolio-state-reconstruction")
def reconstruct_portfolio_state(
    request: PortfolioStateReconstructionRequest,
) -> dict[str, object]:
    """Reconstruct historical cash and long positions from observed ledger events only."""

    service = _service()
    try:
        result = service.evaluate(
            as_of=_aware_utc(request.asOf, "asOf"),
            item=RecommendationPortfolioStateReconstructionInput(
                portfolio_id=request.portfolioId,
                reporting_currency=request.reportingCurrency,
                reconstruction_start=_aware_utc(
                    request.reconstructionStart,
                    "reconstructionStart",
                ),
                opening_cash=OpeningCashEvidence(
                    balance=request.openingCash.balance,
                    currency=request.openingCash.currency,
                    observed_at=_aware_utc(
                        request.openingCash.observedAt,
                        "openingCash.observedAt",
                    ),
                    available_at=_aware_utc(
                        request.openingCash.availableAt,
                        "openingCash.availableAt",
                    ),
                    source=request.openingCash.source,
                    source_ref=request.openingCash.sourceRef,
                ),
                opening_positions=tuple(
                    OpeningPositionEvidence(
                        instrument_id=item.instrumentId,
                        quantity=item.quantity,
                        observed_at=_aware_utc(
                            item.observedAt,
                            f"openingPositions[{index}].observedAt",
                        ),
                        available_at=_aware_utc(
                            item.availableAt,
                            f"openingPositions[{index}].availableAt",
                        ),
                        source=item.source,
                        source_ref=item.sourceRef,
                    )
                    for index, item in enumerate(request.openingPositions)
                ),
            ),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo reconstruir el estado histórico de cartera.",
        ) from exc

    payload = result.to_api_dict()
    if _SHA256_RE.fullmatch(str(payload.get("portfolioStateKey", ""))) is None:
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconstruction devolvió identidad inválida.",
        )
    if (
        payload.get("advisoryStatus") != "no_advice"
        or payload.get("productionEligible") is not False
        or payload.get("isWeightingReady") is not False
    ):
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconstruction violó los límites de seguridad.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="Portfolio state reconstruction intentó habilitar trading.",
        )
    return {"data": payload}


@router.post("/portfolio-state-reconciliation")
def reconcile_portfolio_state(
    request: PortfolioStateReconciliationRequest,
) -> dict[str, object]:
    """Reconcile state and persist the exact PIT evidence append-only."""

    try:
        result = RecommendationPortfolioStateReconciliationService().evaluate(
            as_of=_aware_utc(request.asOf, "asOf"),
            item=PortfolioStateReconciliationInput(
                reconstructed_state=request.reconstructedState,
                snapshot=PortfolioSnapshotEvidence(
                    portfolio_id=request.snapshot.portfolioId,
                    reporting_currency=request.snapshot.reportingCurrency,
                    cash_balance=request.snapshot.cashBalance,
                    positions=tuple(
                        PortfolioSnapshotPositionEvidence(
                            instrument_id=item.instrumentId,
                            quantity=item.quantity,
                        )
                        for item in request.snapshot.positions
                    ),
                    observed_at=_aware_utc(
                        request.snapshot.observedAt,
                        "snapshot.observedAt",
                    ),
                    available_at=_aware_utc(
                        request.snapshot.availableAt,
                        "snapshot.availableAt",
                    ),
                    source=request.snapshot.source,
                    source_ref=request.snapshot.sourceRef,
                ),
            ),
        )
        payload = result.to_api_dict()
        _assert_reconciliation_contract(payload)
        record = _reconciliation_repository.append(artifact=payload)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo reconciliar/persistir el estado histórico de cartera.",
        ) from exc

    return {
        "data": payload,
        "persistence": {
            "appendOnly": True,
            "tamperEvidence": "canonical_artifact_sha256",
            "artifactHash": record["artifact_hash"],
            "createdAt": record["created_at"],
        },
    }


@router.get("/portfolio-state-reconciliation/{reconciliation_key}")
def get_portfolio_state_reconciliation(reconciliation_key: str) -> dict[str, object]:
    """Read a persisted reconciliation only after tamper verification."""

    try:
        record = _reconciliation_repository.get_by_key(
            reconciliation_key=reconciliation_key,
        )
        payload = record["artifact"]
        _assert_reconciliation_contract(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar la reconciliación persistida.",
        ) from exc
    return {
        "data": payload,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
            "createdAt": record["created_at"],
        },
    }
