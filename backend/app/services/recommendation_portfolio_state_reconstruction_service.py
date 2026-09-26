from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Iterable

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEvent,
    RecommendationPortfolioEventLedgerService,
)


@dataclass(frozen=True)
class OpeningCashEvidence:
    balance: float
    currency: str
    observed_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class OpeningPositionEvidence:
    instrument_id: str
    quantity: float
    observed_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class RecommendationPortfolioStateReconstructionInput:
    portfolio_id: str
    reporting_currency: str
    reconstruction_start: datetime
    opening_cash: OpeningCashEvidence
    opening_positions: tuple[OpeningPositionEvidence, ...]


@dataclass(frozen=True)
class RecommendationPortfolioStateReconstructionResult:
    state_key: str
    portfolio_id: str
    reporting_currency: str
    reconstruction_start: datetime
    as_of: datetime
    cash_balance: float
    positions: tuple[dict[str, object], ...]
    applied_event_keys: tuple[str, ...]

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "portfolio_state_reconstruction",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "portfolioStateKey": self.state_key,
            "portfolioId": self.portfolio_id,
            "reportingCurrency": self.reporting_currency,
            "reconstructionStart": self.reconstruction_start.isoformat(),
            "asOf": self.as_of.isoformat(),
            "cashBalance": self.cash_balance,
            "positions": [dict(item) for item in self.positions],
            "appliedEventKeys": list(self.applied_event_keys),
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "orderPlacement": "forbidden",
                "cashInference": "forbidden",
                "fxInference": "forbidden",
                "shorting": "unsupported_fail_closed",
                "margin": "unsupported_fail_closed",
                "corporateActions": "typed_cash_dividend_fee_tax_and_split_supported_generic_action_fail_closed",
                "typedEventSemantics": {
                    "externalCashFlow": "cash_only_external_capital",
                    "tradeExecution": "explicit_cash_and_quantity_effect",
                    "cashDividend": "internal_cash_only",
                    "fee": "internal_negative_cash_only",
                    "tax": "internal_negative_cash_only",
                    "splitAdjustment": "quantity_only_no_cash",
                    "corporateAction": "generic_form_rejected",
                },
                "temporal": "opening_available_at_lte_start_and_event_available_at_lte_as_of",
                "identity": "deterministic_sha256_portfolio_state_key",
                "purpose": "historical_position_and_cash_reconstruction_only",
            },
        }


class RecommendationPortfolioStateReconstructionService:
    _ABS_TOLERANCE = 1e-10
    _CASH_EVENT_TYPES = frozenset(
        {"external_cash_flow", "trade_execution", "cash_dividend", "fee", "tax"}
    )

    def __init__(self, ledger: RecommendationPortfolioEventLedgerService):
        self._ledger = ledger

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _text(value: str, field: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"{field} is required")
        return cleaned

    @classmethod
    def _currency(cls, value: str, field: str) -> str:
        cleaned = cls._text(value, field).upper()
        if len(cleaned) != 3 or not cleaned.isascii() or not cleaned.isalpha():
            raise ValueError(f"{field} must be a three-letter currency code")
        return cleaned

    @staticmethod
    def _finite(value: float, field: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    def _opening_cash(
        self,
        evidence: OpeningCashEvidence,
        *,
        start: datetime,
        reporting_currency: str,
    ) -> tuple[float, dict[str, str]]:
        balance = self._finite(evidence.balance, "opening_cash.balance")
        if balance < 0.0:
            raise ValueError("opening_cash.balance cannot be negative without explicit margin semantics")
        currency = self._currency(evidence.currency, "opening_cash.currency")
        if currency != reporting_currency:
            raise ValueError("opening cash currency requires explicit FX conversion evidence")
        observed = self._aware_utc(evidence.observed_at, "opening_cash.observed_at")
        available = self._aware_utc(evidence.available_at, "opening_cash.available_at")
        if observed != start:
            raise ValueError("opening_cash.observed_at must equal reconstruction_start")
        if observed > available or available > start:
            raise ValueError("opening cash violates observed_at <= available_at <= reconstruction_start")
        return balance, {
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "source": self._text(evidence.source, "opening_cash.source"),
            "sourceRef": self._text(evidence.source_ref, "opening_cash.source_ref"),
        }

    def _opening_positions(
        self,
        items: Iterable[OpeningPositionEvidence],
        *,
        start: datetime,
    ) -> tuple[dict[str, float], tuple[dict[str, object], ...]]:
        positions: dict[str, float] = {}
        evidence_payloads: list[dict[str, object]] = []
        seen_refs: set[tuple[str, str]] = set()
        for index, item in enumerate(items):
            instrument = self._text(item.instrument_id, f"opening_positions[{index}].instrument_id")
            if instrument in positions:
                raise ValueError("opening positions contain duplicate instrument identity")
            quantity = self._finite(item.quantity, f"opening_positions[{index}].quantity")
            if quantity < 0.0:
                raise ValueError("opening position cannot be negative without explicit short semantics")
            observed = self._aware_utc(item.observed_at, f"opening_positions[{index}].observed_at")
            available = self._aware_utc(item.available_at, f"opening_positions[{index}].available_at")
            if observed != start:
                raise ValueError("opening position observed_at must equal reconstruction_start")
            if observed > available or available > start:
                raise ValueError("opening position violates observed_at <= available_at <= reconstruction_start")
            source = self._text(item.source, f"opening_positions[{index}].source")
            source_ref = self._text(item.source_ref, f"opening_positions[{index}].source_ref")
            provenance = (source, source_ref)
            if provenance in seen_refs:
                raise ValueError("opening positions contain duplicate provenance")
            seen_refs.add(provenance)
            if quantity > self._ABS_TOLERANCE:
                positions[instrument] = quantity
            evidence_payloads.append(
                {
                    "instrumentId": instrument,
                    "quantity": quantity,
                    "observedAt": observed.isoformat(),
                    "availableAt": available.isoformat(),
                    "source": source,
                    "sourceRef": source_ref,
                }
            )
        evidence_payloads.sort(key=lambda item: str(item["instrumentId"]))
        return positions, tuple(evidence_payloads)

    @staticmethod
    def _state_key(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _eligible_events(
        self,
        *,
        portfolio_id: str,
        start: datetime,
        as_of: datetime,
    ) -> tuple[PortfolioLedgerEvent, ...]:
        events = [
            record.event
            for record in self._ledger.load()
            if record.event.portfolio_id == portfolio_id
            and start < record.event.occurred_at <= as_of
            and record.event.available_at <= as_of
        ]
        events.sort(key=lambda event: (event.occurred_at, event.available_at, event.event_key))
        return tuple(events)

    def evaluate(
        self,
        *,
        as_of: datetime,
        item: RecommendationPortfolioStateReconstructionInput,
    ) -> RecommendationPortfolioStateReconstructionResult:
        cutoff = self._aware_utc(as_of, "as_of")
        start = self._aware_utc(item.reconstruction_start, "reconstruction_start")
        if cutoff <= start:
            raise ValueError("as_of must be after reconstruction_start")
        portfolio_id = self._text(item.portfolio_id, "portfolio_id")
        reporting_currency = self._currency(item.reporting_currency, "reporting_currency")
        cash, opening_cash_meta = self._opening_cash(
            item.opening_cash,
            start=start,
            reporting_currency=reporting_currency,
        )
        positions, opening_position_meta = self._opening_positions(
            item.opening_positions,
            start=start,
        )

        events = self._eligible_events(
            portfolio_id=portfolio_id,
            start=start,
            as_of=cutoff,
        )
        applied_keys: list[str] = []

        index = 0
        while index < len(events):
            occurred_at = events[index].occurred_at
            cash_delta = 0.0
            position_deltas: dict[str, float] = {}
            while index < len(events) and events[index].occurred_at == occurred_at:
                event = events[index]
                if event.event_type == "corporate_action":
                    raise ValueError("corporate_action requires typed semantics before state reconstruction")
                if event.event_type in self._CASH_EVENT_TYPES and event.currency != reporting_currency:
                    raise ValueError("portfolio cash event currency requires explicit FX conversion evidence")

                if event.event_type == "external_cash_flow":
                    assert event.amount is not None
                    cash_delta += event.amount
                elif event.event_type == "trade_execution":
                    assert event.amount is not None and event.quantity is not None and event.instrument_id is not None
                    cash_delta += event.amount
                    position_deltas[event.instrument_id] = (
                        position_deltas.get(event.instrument_id, 0.0) + event.quantity
                    )
                elif event.event_type in {"cash_dividend", "fee", "tax"}:
                    assert event.amount is not None
                    cash_delta += event.amount
                elif event.event_type == "split_adjustment":
                    assert event.quantity is not None and event.instrument_id is not None
                    position_deltas[event.instrument_id] = (
                        position_deltas.get(event.instrument_id, 0.0) + event.quantity
                    )
                else:
                    raise ValueError("unsupported portfolio event in state reconstruction")
                applied_keys.append(event.event_key)
                index += 1

            cash = self._finite(cash + cash_delta, "reconstructed cash balance")
            if cash < -self._ABS_TOLERANCE:
                raise ValueError("portfolio reconstruction would require unsupported margin borrowing")
            if abs(cash) <= self._ABS_TOLERANCE:
                cash = 0.0

            for instrument, delta in position_deltas.items():
                quantity = self._finite(
                    positions.get(instrument, 0.0) + delta,
                    f"reconstructed quantity for {instrument}",
                )
                if quantity < -self._ABS_TOLERANCE:
                    raise ValueError("portfolio reconstruction would require unsupported short position")
                if abs(quantity) <= self._ABS_TOLERANCE:
                    positions.pop(instrument, None)
                else:
                    positions[instrument] = quantity

        position_payloads = tuple(
            {"instrumentId": instrument, "quantity": positions[instrument]}
            for instrument in sorted(positions)
        )
        identity_payload: dict[str, object] = {
            "schema": "athena_portfolio_state_reconstruction_v1",
            "portfolioId": portfolio_id,
            "reportingCurrency": reporting_currency,
            "reconstructionStart": start.isoformat(),
            "asOf": cutoff.isoformat(),
            "openingCash": {
                "balance": format(self._finite(item.opening_cash.balance, "opening_cash.balance"), ".17g"),
                **opening_cash_meta,
            },
            "openingPositions": list(opening_position_meta),
            "appliedEventKeys": sorted(applied_keys),
            "cashBalance": format(cash, ".17g"),
            "positions": [
                {"instrumentId": str(position["instrumentId"]), "quantity": format(float(position["quantity"]), ".17g")}
                for position in position_payloads
            ],
        }
        state_key = self._state_key(identity_payload)
        return RecommendationPortfolioStateReconstructionResult(
            state_key=state_key,
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            reconstruction_start=start,
            as_of=cutoff,
            cash_balance=cash,
            positions=position_payloads,
            applied_event_keys=tuple(sorted(applied_keys)),
        )
