from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.athena_readiness_service import build_readiness_report


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
