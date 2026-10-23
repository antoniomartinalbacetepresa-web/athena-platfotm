from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.athena_readiness_service import build_readiness_report
from app.services.deployment_security_readiness_service import (
    DeploymentSecurityReadinessService,
)
from app.services.market_history_gap_service import MarketHistoryGapService


router = APIRouter(
    prefix="/api/v1/readiness",
    tags=["readiness"],
)


@router.get("")
def get_readiness() -> dict[str, Any]:
    """Return ATHENA's evidence-backed operational readiness diagnostics.

    This endpoint is intentionally read-only. It cannot promote a model,
    activate weighting, authorize allocation, or execute trades.
    """

    return build_readiness_report()


@router.get("/security")
def get_deployment_security_readiness() -> dict[str, Any]:
    """Return non-secret deployment security configuration diagnostics.

    The response reports only boolean properties and blocker identifiers. It
    deliberately does not claim that production SMTP, off-site backups or
    secret rotation have been operationally verified.
    """

    return DeploymentSecurityReadinessService().evaluate().to_api_dict()


@router.get("/market-history/gaps")
def get_market_history_gaps(
    as_of: datetime | None = Query(None, alias="asOf"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Page PIT history blockers without fetching data or promoting readiness.

    The active instrument catalog is not a historical membership snapshot.
    Every observation is filtered by both observedAt and retrievedAt.
    """
    try:
        report = MarketHistoryGapService().get_report(
            as_of=as_of, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="No se pudo evaluar el diagnóstico PIT de huecos históricos.",
        ) from exc
    return report.to_api_dict()
