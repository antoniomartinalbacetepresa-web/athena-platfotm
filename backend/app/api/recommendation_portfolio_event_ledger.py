from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.security.portfolio_owner_storage import owner_scoped_ledger_path
from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_LEDGER_PATH = "var/athena/portfolio_event_ledger.jsonl"


class PortfolioLedgerEventRequest(BaseModel):
    portfolioId: str = Field(min_length=1)
    eventType: str = Field(min_length=1)
    occurredAt: datetime
    availableAt: datetime
    currency: str = Field(min_length=3, max_length=3)
    amount: float | None = None
    instrumentId: str | None = None
    quantity: float | None = None
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    asOf: datetime


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _service() -> RecommendationPortfolioEventLedgerService:
    configured = os.environ.get("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", _DEFAULT_LEDGER_PATH).strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Portfolio event ledger no tiene ruta de persistencia configurada.")
    return RecommendationPortfolioEventLedgerService(owner_scoped_ledger_path(Path(configured)))


def _policy_payload(service: RecommendationPortfolioEventLedgerService) -> dict[str, object]:
    policy = service.policy()
    if policy.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Portfolio ledger violó no_advice.")
    if policy.get("productionEligible") is not False or policy.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Portfolio ledger intentó habilitar producción/weighting.")
    if policy.get("automaticTrading") is not False or policy.get("orderPlacement") != "forbidden":
        raise HTTPException(status_code=500, detail="Portfolio ledger intentó habilitar trading.")
    return policy


@router.post("/portfolio-event-ledger/events")
def append_portfolio_event(request: PortfolioLedgerEventRequest) -> dict[str, object]:
    """Persist an already-observed portfolio event. This endpoint never creates or routes orders."""

    service = _service()
    try:
        record = service.append(
            as_of=_aware_utc(request.asOf, "asOf"),
            item=PortfolioLedgerEventInput(
                portfolio_id=request.portfolioId,
                event_type=request.eventType,
                occurred_at=_aware_utc(request.occurredAt, "occurredAt"),
                available_at=_aware_utc(request.availableAt, "availableAt"),
                currency=request.currency,
                amount=request.amount,
                instrument_id=request.instrumentId,
                quantity=request.quantity,
                source=request.source,
                source_ref=request.sourceRef,
            ),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo persistir el evento histórico de cartera.") from exc
    if _SHA256_RE.fullmatch(record.event.event_key) is None or _SHA256_RE.fullmatch(record.record_hash) is None:
        raise HTTPException(status_code=500, detail="Portfolio ledger devolvió identidad inválida.")
    return {
        "data": {
            "module": "portfolio_event_ledger",
            "record": record.to_dict(),
            "policy": _policy_payload(service),
        }
    }


@router.get("/portfolio-event-ledger/external-cash-flows")
def get_external_cash_flows(
    portfolioId: str = Query(min_length=1),
    reportingCurrency: str = Query(min_length=3, max_length=3),
    periodStart: datetime = Query(),
    periodEnd: datetime = Query(),
    asOf: datetime = Query(),
) -> dict[str, object]:
    """Project persisted external flows for historical TWR boundaries without FX inference."""

    service = _service()
    try:
        flows = service.external_cash_flows(
            portfolio_id=portfolioId,
            reporting_currency=reportingCurrency,
            period_start=_aware_utc(periodStart, "periodStart"),
            period_end=_aware_utc(periodEnd, "periodEnd"),
            as_of=_aware_utc(asOf, "asOf"),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo proyectar cash flow histórico de cartera.") from exc
    return {
        "data": {
            "module": "portfolio_event_ledger_external_cash_flows",
            "portfolioId": portfolioId,
            "reportingCurrency": reportingCurrency.upper(),
            "flows": [item.to_api_dict() for item in flows],
            "policy": _policy_payload(service),
        }
    }
