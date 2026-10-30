"""Public, non-secret runtime source marker for deployed acceptance.

The SHA must be supplied by trusted deployment automation. This is a
runtime configuration assertion, not cryptographic build attestation.
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException, Response


router = APIRouter()


@router.get("/api/v1/build")
def backend_build_identity(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    sha = os.environ.get("ATHENA_DEPLOYED_SOURCE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise HTTPException(
            status_code=503,
            detail="Build identity unavailable",
            headers={"Cache-Control": "no-store"},
        )
    return {"schema": "athena.backend-build.v1", "sourceSha": sha}
