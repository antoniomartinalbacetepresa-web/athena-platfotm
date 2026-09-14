from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.athena_readiness_service import build_readiness_report
from app.services.deployment_security_readiness_service import (
    DeploymentSecurityReadinessService,
)


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
