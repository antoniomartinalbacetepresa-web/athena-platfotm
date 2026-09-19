from __future__ import annotations

from datetime import datetime
from typing import Any

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)


class RecommendationPortfolioIntegrityGate:
    """Require a persisted, tamper-verified, reconciled PIT portfolio state."""

    def __init__(
        self,
        repository: RecommendationPortfolioStateReconciliationRepository | None = None,
    ) -> None:
        self._repository = repository or RecommendationPortfolioStateReconciliationRepository()

    def require(
        self,
        *,
        reconciliation_key: str,
        portfolio_id: str,
        reporting_currency: str,
        as_of: datetime,
        purpose: str,
    ) -> dict[str, Any]:
        record = self._repository.require_reconciled(
            reconciliation_key=reconciliation_key,
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            as_of=as_of,
        )
        return {
            "reconciliationKey": record["reconciliation_key"],
            "portfolioStateKey": record["portfolio_state_key"],
            "reconciled": True,
            "tamperVerified": True,
            "gate": f"required_before_{purpose}",
        }
