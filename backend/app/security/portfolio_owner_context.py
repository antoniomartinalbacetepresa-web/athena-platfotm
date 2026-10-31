from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Annotated, Any, AsyncIterator, Iterator

from fastapi import Depends, HTTPException, status

from app.api.auth import current_account


_PORTFOLIO_OWNER_ID: ContextVar[int | None] = ContextVar(
    "athena_portfolio_owner_user_id",
    default=None,
)


def _validated_owner_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales no válidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return value


def current_portfolio_owner_id() -> int:
    owner_user_id = _PORTFOLIO_OWNER_ID.get()
    if owner_user_id is None:
        raise ValueError("portfolio owner context is required")
    return _validated_owner_id(owner_user_id)


async def bind_portfolio_owner_context(
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> AsyncIterator[None]:
    """Bind the authenticated owner for the lifetime of the request task.

    This dependency is intentionally async so ContextVar set/reset happens in
    the same event-loop task. A synchronous generator dependency may be entered
    and exited in different worker-thread contexts, which is unsafe for tokens.
    """

    owner_user_id = _validated_owner_id(account.get("id"))
    token: Token[int | None] = _PORTFOLIO_OWNER_ID.set(owner_user_id)
    try:
        yield
    finally:
        _PORTFOLIO_OWNER_ID.reset(token)


@contextmanager
def portfolio_owner_scope(owner_user_id: int) -> Iterator[None]:
    """Explicit scope for trusted internal jobs and deterministic tests."""

    validated = _validated_owner_id(owner_user_id)
    token: Token[int | None] = _PORTFOLIO_OWNER_ID.set(validated)
    try:
        yield
    finally:
        _PORTFOLIO_OWNER_ID.reset(token)
