from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.auth import current_account
from app.repositories.encrypted_user_profile_repository import EncryptedUserProfileRepository


router = APIRouter(prefix="/api/v1/user/profile", tags=["user-profile"])


class UserPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    riskTolerance: Literal["conservative", "balanced", "growth", "aggressive"]
    investmentHorizonYears: int = Field(ge=1, le=60)
    baseCurrency: str = Field(min_length=3, max_length=3)
    objective: Literal[
        "capital_preservation",
        "income",
        "balanced_growth",
        "long_term_growth",
    ]
    experienceLevel: Literal["beginner", "intermediate", "advanced"] | None = None
    liquidityNeed: Literal["low", "medium", "high"] | None = None
    maxDrawdownTolerancePct: int | None = Field(default=None, ge=5, le=60)
    # Range/finite validation is intentionally performed in the route instead
    # of as a Pydantic numeric constraint. Python's JSON decoder accepts the
    # non-standard NaN/Infinity constants; if those reach a Pydantic numeric
    # constraint, FastAPI includes the non-finite input in its validation
    # detail and Starlette cannot serialize that error as strict JSON. Keeping
    # the type here and enforcing the financial boundary below makes those
    # hostile/non-standard payloads fail closed with a deterministic 422.
    availableCapital: float | None = None

    @field_validator("baseCurrency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
            raise ValueError("baseCurrency debe ser un código ISO de tres letras.")
        return normalized


def _repository() -> EncryptedUserProfileRepository:
    try:
        return EncryptedUserProfileRepository()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento cifrado del perfil no está configurado de forma segura.",
        ) from exc


def _owner_id(account: dict[str, Any]) -> int:
    try:
        owner_id = int(account["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales no válidas.",
        ) from exc
    if owner_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales no válidas.",
        )
    return owner_id


def _validated_available_capital(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < 0 or value > 1_000_000_000_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "availableCapital debe ser un número finito entre 0 y "
                "1000000000000, denominado en baseCurrency."
            ),
        )
    return value


def _policy() -> dict[str, Any]:
    return {
        "ownerDerivedFromAuthenticatedToken": True,
        "clientSuppliedOwnerAccepted": False,
        "sensitivePreferencesEncrypted": True,
        "encryption": "AES-256-GCM",
        "keyManagedExternally": True,
        "encryptedPreferenceFields": [
            "riskTolerance",
            "investmentHorizonYears",
            "baseCurrency",
            "objective",
            "experienceLevel",
            "liquidityNeed",
            "maxDrawdownTolerancePct",
            "availableCapital",
        ],
        "automaticRecommendationOverrides": False,
        "productionEligible": False,
        "automaticTrading": False,
    }


@router.get("/preferences")
def get_preferences(
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, Any]:
    repository = _repository()
    try:
        stored = repository.get_for_owner(_owner_id(account))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="El perfil cifrado no supera la verificación de integridad.",
        ) from exc
    return {
        "status": "configured" if stored is not None else "not_configured",
        "data": stored,
        "policy": _policy(),
    }


@router.put("/preferences")
def put_preferences(
    payload: UserPreferencesRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, Any]:
    preferences = payload.model_dump()
    preferences["availableCapital"] = _validated_available_capital(payload.availableCapital)
    repository = _repository()
    stored = repository.upsert(
        owner_user_id=_owner_id(account),
        preferences=preferences,
    )
    return {"status": "configured", "data": stored, "policy": _policy()}


@router.delete("/preferences", status_code=status.HTTP_204_NO_CONTENT)
def delete_preferences(
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> Response:
    repository = _repository()
    repository.delete_for_owner(_owner_id(account))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
