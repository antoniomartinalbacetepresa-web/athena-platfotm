from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.repositories.recommendation_portfolio_event_journal_repository import (
    RecommendationPortfolioEventJournalRepository,
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
class PersistedLedgerPortfolioTwrResult:
    core: LedgerBoundPortfolioTwrResult
    selected_event_count: int
    last_selected_record_fingerprint: str | None

    def to_api_dict(self) -> dict[str, object]:
        payload = self.core.to_api_dict()
        payload["status"] = "measured_from_server_side_persisted_portfolio_event_journal"
        payload["persistedLedger"] = {
            "serverSide": True,
            "appendOnly": True,
            "tamperEvidentHashChain": True,
            "selectedEventCount": self.selected_event_count,
            "lastSelectedRecordFingerprint": self.last_selected_record_fingerprint,
        }
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("TWR result lost policy")
        policy["callerSuppliedExternalCashFlowLedger"] = False
        policy["automaticTrading"] = False
        payload["advisoryStatus"] = "no_advice"
        payload["productionEligible"] = False
        payload["isWeightingReady"] = False
        return payload


class RecommendationPortfolioPersistedTwrService:
    """Rebuilds TWR using external cash-flow evidence read from the server journal."""

    def __init__(
        self,
        *,
        journal_repository: RecommendationPortfolioEventJournalRepository | None = None,
        ledger_binding_service: RecommendationPortfolioTwrLedgerBindingService | None = None,
    ) -> None:
        self._journal = journal_repository or RecommendationPortfolioEventJournalRepository()
        self._ledger_binding = ledger_binding_service or RecommendationPortfolioTwrLedgerBindingService()

    def evaluate(
        self,
        *,
        tenant_id: str,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
        boundaries: Iterable[PortfolioTwrBoundaryInput],
        internal_cash_events: Iterable[PortfolioTwrInternalCashEventInput] = (),
    ) -> PersistedLedgerPortfolioTwrResult:
        records = self._journal.scan_external_cash_flows(
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        flows = tuple(
            PortfolioTwrExternalFlowEventInput(
                event_key=str(record["event_key"]),
                amount=float(record["amount"]),
                currency=str(record["currency"]),
                occurred_at=self._aware_iso(str(record["occurred_at"]), "occurred_at"),
                available_at=self._aware_iso(str(record["available_at"]), "available_at"),
                source=str(record["source"]),
                source_ref=str(record["source_ref"]),
            )
            for record in records
        )
        core = self._ledger_binding.evaluate(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            boundaries=boundaries,
            external_cash_flows=flows,
            internal_cash_events=internal_cash_events,
        )
        head = records[-1]["record_fingerprint"] if records else None
        return PersistedLedgerPortfolioTwrResult(
            core=core,
            selected_event_count=len(records),
            last_selected_record_fingerprint=None if head is None else str(head),
        )

    @staticmethod
    def _aware_iso(value: str, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be valid ISO datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return parsed.astimezone(timezone.utc)
