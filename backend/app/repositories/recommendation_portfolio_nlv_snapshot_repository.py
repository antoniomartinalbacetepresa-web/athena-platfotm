from __future__ import annotations

from typing import Any

from app.repositories.recommendation_portfolio_nlv_snapshot_repository_core import (
    RecommendationPortfolioNlvSnapshotRepository as _OwnerScopedCore,
)
from app.security.portfolio_owner_context import current_portfolio_owner_id


class RecommendationPortfolioNlvSnapshotRepository(_OwnerScopedCore):
    """Request-owner adapter over the owner-scoped v2 NLV store.

    Public APIs never accept owner identity from the caller payload. Trusted
    internal jobs/tests may pass owner_user_id explicitly; otherwise the owner
    must have been bound from authenticated account context.
    """

    @staticmethod
    def _resolved_owner(owner_user_id: int | None) -> int:
        if owner_user_id is not None:
            return _OwnerScopedCore._owner_user_id(owner_user_id)
        return current_portfolio_owner_id()

    def append(
        self,
        *,
        owner_user_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return super().append(
            owner_user_id=self._resolved_owner(owner_user_id),
            **kwargs,
        )

    def get_by_key(
        self,
        *,
        snapshot_key: str,
        owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        return super().get_by_key(
            owner_user_id=self._resolved_owner(owner_user_id),
            snapshot_key=snapshot_key,
        )

    def require_snapshot(
        self,
        *,
        snapshot_key: str,
        owner_user_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return super().require_snapshot(
            owner_user_id=self._resolved_owner(owner_user_id),
            snapshot_key=snapshot_key,
            **kwargs,
        )
