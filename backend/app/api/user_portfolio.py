from __future__ import annotations

import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_account
from app.repositories.user_portfolio_repository import UserPortfolioRepository


router = APIRouter(
    prefix="/api/v1/user/portfolio",
    tags=["user-portfolio"],
)


class PositionUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    exchange: str | None = Field(default=None, max_length=32)
    quantity: float = Field(gt=0, le=1_000_000_000_000)
    # Keep finiteness/range validation at the HTTP boundary below. Pydantic can
    # accept IEEE-754 NaN/Infinity as floats; raising a model validation error
    # that embeds those values can itself become non-JSON-serializable.
    averagePurchasePrice: float | None = None


def _repository() -> UserPortfolioRepository:
    return UserPortfolioRepository()


def _owner_id(account: dict[str, Any]) -> int:
    user_id = account.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales no válidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


def _policy() -> dict[str, bool]:
    return {
        "ownerDerivedFromAuthenticatedToken": True,
        "clientSuppliedOwnerAccepted": False,
        "sensitiveCostBasisStored": True,
        "sensitiveCostBasisEncrypted": True,
        # Symbol/exchange/quantity remain queryable operational state. Do not
        # misrepresent the whole table as encrypted at rest.
        "storageEncrypted": False,
        "productionEligible": False,
        "automaticTrading": False,
    }


@router.get("")
def get_personal_portfolio(
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, Any]:
    owner_id = _owner_id(account)
    try:
        positions = _repository().list_for_owner(owner_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="No se pudo descifrar la cartera personal.") from exc
    return {
        "data": {
            "positions": positions,
            "positionCount": len(positions),
        },
        "policy": _policy(),
    }


@router.put("/positions")
def put_personal_portfolio_position(
    payload: PositionUpsertRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, Any]:
    owner_id = _owner_id(account)
    average_purchase_price = payload.averagePurchasePrice
    if average_purchase_price is not None:
        if (
            not math.isfinite(average_purchase_price)
            or average_purchase_price <= 0
            or average_purchase_price > 1_000_000_000_000
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "averagePurchasePrice debe ser numérico finito, positivo "
                    "y estar dentro del límite operativo."
                ),
            )
    try:
        position = _repository().upsert(
            owner_user_id=owner_id,
            symbol=payload.symbol,
            exchange=payload.exchange,
            quantity=payload.quantity,
            average_purchase_price=average_purchase_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Cifrado de cartera personal no disponible.") from exc
    return {
        "data": position,
        "policy": _policy(),
    }


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_personal_portfolio_position(
    position_id: int,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> None:
    owner_id = _owner_id(account)
    deleted = _repository().delete_for_owner(
        owner_user_id=owner_id,
        position_id=position_id,
    )
    if not deleted:
        # A foreign user's position is deliberately indistinguishable from a
        # nonexistent position, preventing cross-account enumeration.
        raise HTTPException(status_code=404, detail="Posición no encontrada.")
