from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
)
from app.services.recommendation_portfolio_twr_ledger_binding_service import (
    LedgerBoundPortfolioTwrResult,
    PortfolioTwrExternalFlowEventInput,
    RecommendationPortfolioTwrLedgerBindingService,
)
from app.services.recommendation_portfolio_twr_measurement_service import (
    PortfolioTwrBoundaryInput,
    PortfolioTwrInternalCashEventInput,
)


@dataclass(frozen=True)
class ServerSidePortfolioTwrResult:
    core: LedgerBoundPortfolioTwrResult
    external_event_count: int
    internal_event_count: int
    ledger_head_hash: str

    def to_api_dict(self) -> dict[str, object]:
        payload = self.core.to_api_dict()
        payload["status"] = "measured_from_canonical_server_side_portfolio_ledger"
        payload["serverSideLedger"] = {
            "callerSuppliedEventsAccepted": False,
            "appendOnly": True,
            "tamperEvidentHashChain": True,
            "externalEventCount": self.external_event_count,
            "internalEventCount": self.internal_event_count,
            "ledgerHeadHash": self.ledger_head_hash,
        }
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("server-side TWR result lost policy")
        policy["callerSuppliedExternalCashFlowLedger"] = False
        policy["callerSuppliedInternalCashEvents"] = False
        policy["automaticTrading"] = False
        policy["automaticProductionPromotion"] = False
        payload["advisoryStatus"] = "no_advice"
        payload["productionEligible"] = False
        payload["isWeightingReady"] = False
        return payload


class RecommendationPortfolioServerSideTwrService:
    """Measure TWR using the canonical server-side portfolio event ledger.

    Valuation boundaries remain explicit PIT evidence. Portfolio cash events do
    not: external flows, dividends, fees and taxes are selected from the same
    append-only ledger used by portfolio-state reconstruction. This prevents a
    caller from omitting a contribution or inventing an internal cash event to
    alter measured performance.
    """

    def __init__(
        self,
        *,
        ledger_path: str | Path,
        ledger_binding_service: RecommendationPortfolioTwrLedgerBindingService | None = None,
    ) -> None:
        self._ledger = RecommendationPortfolioEventLedgerService(ledger_path)
        self._ledger_binding = ledger_binding_service or RecommendationPortfolioTwrLedgerBindingService()

    def evaluate(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
        boundaries: Iterable[PortfolioTwrBoundaryInput],
    ) -> ServerSidePortfolioTwrResult:
        external = self._ledger.external_cash_flows(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        internal = self._ledger.internal_cash_events(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        external_inputs = tuple(
            PortfolioTwrExternalFlowEventInput(
                event_key=item.event_key,
                amount=item.amount,
                currency=item.currency,
                occurred_at=item.occurred_at,
                available_at=item.available_at,
                source=item.source,
                source_ref=item.source_ref,
            )
            for item in external
        )
        internal_inputs = tuple(
            PortfolioTwrInternalCashEventInput(
                event_key=item.event_key,
                event_type=item.event_type,
                amount=item.amount,
                currency=item.currency,
                occurred_at=item.occurred_at,
                available_at=item.available_at,
                source=item.source,
                source_ref=item.source_ref,
            )
            for item in internal
        )
        core = self._ledger_binding.evaluate(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            boundaries=boundaries,
            external_cash_flows=external_inputs,
            internal_cash_events=internal_inputs,
        )
        records = self._ledger.load()
        head = records[-1].record_hash if records else RecommendationPortfolioEventLedgerService.GENESIS_HASH
        return ServerSidePortfolioTwrResult(
            core=core,
            external_event_count=len(external_inputs),
            internal_event_count=len(internal_inputs),
            ledger_head_hash=head,
        )
