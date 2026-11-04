from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import math
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_account
from app.repositories.user_portfolio_repository import UserPortfolioRepository
from app.security.portfolio_owner_storage import owner_scoped_ledger_path
from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
)


router = APIRouter(
    prefix="/api/v1/user/portfolio",
    tags=["user-portfolio"],
)
_DEFAULT_LEDGER_PATH = "var/athena/portfolio_event_ledger.jsonl"
_HISTORY_CURSOR_RE = re.compile(r"^([1-9][0-9]{0,11}):([0-9a-f]{64}):([0-9a-f]{16})$")


def _history_order(record: Any) -> tuple[datetime, datetime, int]:
    return (record.event.occurred_at, record.event.available_at, record.sequence)



class PositionUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    exchange: str | None = Field(default=None, max_length=32)
    # Validate the quantity range at the HTTP boundary as well: non-standard
    # JSON NaN/Infinity values must not enter Pydantic's serialized 422 detail.
    quantity: float
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


def _history_service(owner_user_id: int) -> RecommendationPortfolioEventLedgerService:
    configured = os.environ.get(
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH",
        _DEFAULT_LEDGER_PATH,
    ).strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Historial de cartera no tiene persistencia configurada.",
        )
    return RecommendationPortfolioEventLedgerService(
        owner_scoped_ledger_path(Path(configured), owner_user_id=owner_user_id)
    )


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field} debe incluir zona horaria.",
        )
    return value.astimezone(timezone.utc)


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


def _history_policy() -> dict[str, object]:
    return {
        "ownerDerivedFromAuthenticatedToken": True,
        "clientSuppliedOwnerAccepted": False,
        "sourceOfTruth": "owner_scoped_append_only_event_ledger",
        "pointInTimeFiltered": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "automaticTrading": False,
        "orderPlacement": "forbidden",
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


@router.get("/history")
def get_personal_portfolio_history(
    account: Annotated[dict[str, Any], Depends(current_account)],
    portfolio_id: str = Query(..., alias="portfolioId", min_length=1, max_length=128),
    as_of: datetime = Query(..., alias="asOf"),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, Any]:
    """Read stable pages of the owner's PIT history without crossing ledger generations."""

    owner_id = _owner_id(account)
    cutoff = _aware_utc(as_of, "asOf")
    try:
        records = _history_service(owner_id).load()
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="El historial de cartera no supera la verificación de integridad.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="No se pudo leer el historial de cartera.",
        ) from exc

    # Bind every page to the first page's append-only high-water mark.
    # A later backdated append must not silently change an in-progress page set.
    snapshot_sequence = records[-1].sequence if records else 0
    context = hashlib.sha256(
        f"{portfolio_id}|{cutoff.isoformat()}".encode("utf-8")
    ).hexdigest()[:16]
    anchor_key = None
    if cursor is not None:
        match = _HISTORY_CURSOR_RE.fullmatch(cursor)
        if match is None or match.group(3) != context:
            raise HTTPException(status_code=400, detail="Cursor de historial no válido.")
        snapshot_sequence = int(match.group(1))
        if snapshot_sequence > len(records):
            raise HTTPException(status_code=400, detail="Cursor de historial no válido.")
        anchor = next(
            (
                record for record in records
                if record.sequence <= snapshot_sequence
                and record.record_hash == match.group(2)
                and record.event.portfolio_id == portfolio_id
                and record.event.available_at <= cutoff
            ),
            None,
        )
        if anchor is None:
            raise HTTPException(status_code=400, detail="Cursor de historial no válido.")
        anchor_key = _history_order(anchor)

    visible = [
        record
        for record in records
        if record.sequence <= snapshot_sequence
        and record.event.portfolio_id == portfolio_id
        and record.event.available_at <= cutoff
        and (anchor_key is None or _history_order(record) < anchor_key)
    ]
    visible.sort(key=_history_order, reverse=True)
    selected = visible[:limit]
    has_more = len(visible) > len(selected)
    next_cursor = (
        f"{snapshot_sequence}:{selected[-1].record_hash}:{context}"
        if has_more and selected else None
    )
    return {
        "data": {
            "portfolioId": portfolio_id,
            "asOf": cutoff.isoformat(),
            "nextCursor": next_cursor,
            "events": [
                {
                    "sequence": record.sequence,
                    "recordHash": record.record_hash,
                    **record.event.canonical_dict(),
                }
                for record in selected
            ],
            "eventCount": len(selected),
            "hasMore": has_more,
        },
        "policy": _history_policy(),
    }


@router.put("/positions")
def put_personal_portfolio_position(
    payload: PositionUpsertRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> dict[str, Any]:
    owner_id = _owner_id(account)
    quantity = payload.quantity
    if not math.isfinite(quantity) or quantity <= 0 or quantity > 1_000_000_000_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="quantity debe ser un número finito, positivo y dentro del límite operativo.",
        )
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
            quantity=quantity,
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
