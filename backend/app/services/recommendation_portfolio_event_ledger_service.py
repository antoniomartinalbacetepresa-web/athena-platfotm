from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from threading import Lock
from typing import Iterable


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_EVENT_TYPES = frozenset({"external_cash_flow", "trade_execution", "corporate_action"})


@dataclass(frozen=True)
class PortfolioLedgerEventInput:
    portfolio_id: str
    event_type: str
    occurred_at: datetime
    available_at: datetime
    currency: str
    amount: float | None
    instrument_id: str | None
    quantity: float | None
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioLedgerEvent:
    event_key: str
    portfolio_id: str
    event_type: str
    occurred_at: datetime
    available_at: datetime
    currency: str
    amount: float | None
    instrument_id: str | None
    quantity: float | None
    source: str
    source_ref: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "eventKey": self.event_key,
            "portfolioId": self.portfolio_id,
            "eventType": self.event_type,
            "occurredAt": self.occurred_at.isoformat(),
            "availableAt": self.available_at.isoformat(),
            "currency": self.currency,
            "amount": self.amount,
            "instrumentId": self.instrument_id,
            "quantity": self.quantity,
            "source": self.source,
            "sourceRef": self.source_ref,
        }


@dataclass(frozen=True)
class PortfolioLedgerRecord:
    sequence: int
    previous_hash: str
    record_hash: str
    event: PortfolioLedgerEvent

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "previousHash": self.previous_hash,
            "recordHash": self.record_hash,
            "event": self.event.canonical_dict(),
        }


@dataclass(frozen=True)
class ExternalCashFlowProjection:
    event_key: str
    amount: float
    currency: str
    occurred_at: datetime
    available_at: datetime
    source: str
    source_ref: str

    def to_api_dict(self) -> dict[str, object]:
        return {
            "eventKey": self.event_key,
            "amount": self.amount,
            "currency": self.currency,
            "occurredAt": self.occurred_at.isoformat(),
            "availableAt": self.available_at.isoformat(),
            "source": self.source,
            "sourceRef": self.source_ref,
        }


class RecommendationPortfolioEventLedgerService:
    """Append-only historical research ledger. It records evidence; it never places orders."""

    GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = Lock()

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
    def _currency(cls, value: str) -> str:
        currency = cls._text(value, "currency").upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("currency must be a three-letter currency code")
        return currency

    @staticmethod
    def _finite_optional(value: float | None, field: str) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    @staticmethod
    def _identity_payload(
        *,
        portfolio_id: str,
        event_type: str,
        occurred_at: datetime,
        available_at: datetime,
        currency: str,
        amount: float | None,
        instrument_id: str | None,
        quantity: float | None,
        source: str,
        source_ref: str,
    ) -> str:
        payload = {
            "schema": "athena_portfolio_ledger_event_v1",
            "portfolioId": portfolio_id,
            "eventType": event_type,
            "occurredAt": occurred_at.isoformat(),
            "availableAt": available_at.isoformat(),
            "currency": currency,
            "amount": None if amount is None else format(amount, ".17g"),
            "instrumentId": instrument_id,
            "quantity": None if quantity is None else format(quantity, ".17g"),
            "source": source,
            "sourceRef": source_ref,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def normalize(self, *, as_of: datetime, item: PortfolioLedgerEventInput) -> PortfolioLedgerEvent:
        as_of_utc = self._aware_utc(as_of, "as_of")
        occurred_at = self._aware_utc(item.occurred_at, "occurred_at")
        available_at = self._aware_utc(item.available_at, "available_at")
        if occurred_at > available_at or available_at > as_of_utc:
            raise ValueError("event violates occurred_at <= available_at <= as_of")
        portfolio_id = self._text(item.portfolio_id, "portfolio_id")
        event_type = self._text(item.event_type, "event_type").lower()
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError("unsupported portfolio ledger event_type")
        currency = self._currency(item.currency)
        source = self._text(item.source, "source")
        source_ref = self._text(item.source_ref, "source_ref")
        amount = self._finite_optional(item.amount, "amount")
        quantity = self._finite_optional(item.quantity, "quantity")
        instrument_id = None if item.instrument_id is None else self._text(item.instrument_id, "instrument_id")

        if event_type == "external_cash_flow":
            if amount is None or amount == 0.0:
                raise ValueError("external_cash_flow requires non-zero amount")
            if instrument_id is not None or quantity is not None:
                raise ValueError("external_cash_flow cannot carry instrument identity or quantity")
        elif event_type == "trade_execution":
            if instrument_id is None or quantity is None or quantity == 0.0 or amount is None:
                raise ValueError("trade_execution requires instrument_id, non-zero quantity and explicit amount")
        elif event_type == "corporate_action":
            if instrument_id is None:
                raise ValueError("corporate_action requires instrument_id")
            if amount is None and quantity is None:
                raise ValueError("corporate_action requires explicit amount or quantity effect")

        identity = self._identity_payload(
            portfolio_id=portfolio_id,
            event_type=event_type,
            occurred_at=occurred_at,
            available_at=available_at,
            currency=currency,
            amount=amount,
            instrument_id=instrument_id,
            quantity=quantity,
            source=source,
            source_ref=source_ref,
        )
        event_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return PortfolioLedgerEvent(
            event_key=event_key,
            portfolio_id=portfolio_id,
            event_type=event_type,
            occurred_at=occurred_at,
            available_at=available_at,
            currency=currency,
            amount=amount,
            instrument_id=instrument_id,
            quantity=quantity,
            source=source,
            source_ref=source_ref,
        )

    @staticmethod
    def _record_hash(sequence: int, previous_hash: str, event: PortfolioLedgerEvent) -> str:
        body = json.dumps(event.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(f"portfolio_ledger_record_v1|{sequence}|{previous_hash}|{body}".encode("utf-8")).hexdigest()

    @staticmethod
    def _event_from_dict(payload: dict[str, object]) -> PortfolioLedgerEvent:
        event_key = str(payload.get("eventKey", ""))
        if _SHA256_RE.fullmatch(event_key) is None:
            raise ValueError("portfolio ledger contains invalid event key")
        occurred_at = datetime.fromisoformat(str(payload["occurredAt"]))
        available_at = datetime.fromisoformat(str(payload["availableAt"]))
        return PortfolioLedgerEvent(
            event_key=event_key,
            portfolio_id=str(payload["portfolioId"]),
            event_type=str(payload["eventType"]),
            occurred_at=occurred_at,
            available_at=available_at,
            currency=str(payload["currency"]),
            amount=None if payload.get("amount") is None else float(payload["amount"]),
            instrument_id=None if payload.get("instrumentId") is None else str(payload["instrumentId"]),
            quantity=None if payload.get("quantity") is None else float(payload["quantity"]),
            source=str(payload["source"]),
            source_ref=str(payload["sourceRef"]),
        )

    def _load_unlocked(self) -> tuple[PortfolioLedgerRecord, ...]:
        if not self._path.exists():
            return ()
        records: list[PortfolioLedgerRecord] = []
        expected_previous = self.GENESIS_HASH
        with self._path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                    sequence = int(payload["sequence"])
                    previous_hash = str(payload["previousHash"])
                    record_hash = str(payload["recordHash"])
                    event_payload = payload["event"]
                    if not isinstance(event_payload, dict):
                        raise ValueError("event must be an object")
                    event = self._event_from_dict(event_payload)
                except Exception as exc:
                    raise ValueError(f"portfolio ledger line {line_number} is malformed") from exc
                if sequence != len(records) + 1:
                    raise ValueError("portfolio ledger sequence is not contiguous")
                if previous_hash != expected_previous:
                    raise ValueError("portfolio ledger hash chain is broken")
                if record_hash != self._record_hash(sequence, previous_hash, event):
                    raise ValueError("portfolio ledger record hash is invalid")
                records.append(PortfolioLedgerRecord(sequence, previous_hash, record_hash, event))
                expected_previous = record_hash
        return tuple(records)

    def load(self) -> tuple[PortfolioLedgerRecord, ...]:
        with self._lock:
            return self._load_unlocked()

    def append(self, *, as_of: datetime, item: PortfolioLedgerEventInput) -> PortfolioLedgerRecord:
        event = self.normalize(as_of=as_of, item=item)
        with self._lock:
            records = self._load_unlocked()
            for existing in records:
                if existing.event.event_key == event.event_key:
                    return existing
                if (
                    existing.event.portfolio_id == event.portfolio_id
                    and existing.event.source == event.source
                    and existing.event.source_ref == event.source_ref
                ):
                    raise ValueError("conflicting duplicate provenance in portfolio ledger")
            previous_hash = records[-1].record_hash if records else self.GENESIS_HASH
            sequence = len(records) + 1
            record_hash = self._record_hash(sequence, previous_hash, event)
            record = PortfolioLedgerRecord(sequence, previous_hash, record_hash, event)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True))
                handle.write("\n")
                handle.flush()
            return record

    def external_cash_flows(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> tuple[ExternalCashFlowProjection, ...]:
        portfolio = self._text(portfolio_id, "portfolio_id")
        currency = self._currency(reporting_currency)
        start = self._aware_utc(period_start, "period_start")
        end = self._aware_utc(period_end, "period_end")
        cutoff = self._aware_utc(as_of, "as_of")
        if end <= start or end > cutoff:
            raise ValueError("invalid ledger projection period")
        projected: list[ExternalCashFlowProjection] = []
        for record in self.load():
            event = record.event
            if event.portfolio_id != portfolio or event.event_type != "external_cash_flow":
                continue
            if event.available_at > cutoff or not (start < event.occurred_at < end):
                continue
            if event.currency != currency:
                raise ValueError("external cash flow currency requires explicit FX conversion evidence")
            assert event.amount is not None
            projected.append(
                ExternalCashFlowProjection(
                    event_key=event.event_key,
                    amount=event.amount,
                    currency=event.currency,
                    occurred_at=event.occurred_at,
                    available_at=event.available_at,
                    source=event.source,
                    source_ref=event.source_ref,
                )
            )
        projected.sort(key=lambda item: (item.occurred_at, item.event_key))
        return tuple(projected)

    @staticmethod
    def policy() -> dict[str, object]:
        return {
            "module": "portfolio_event_ledger",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "automaticTrading": False,
            "orderPlacement": "forbidden",
            "cashInference": "forbidden",
            "fxInference": "forbidden",
            "persistence": "append_only_hash_chained_jsonl",
            "temporal": "occurred_at_lte_available_at_lte_as_of",
            "identity": "deterministic_sha256_event_key_and_record_hash_chain",
            "purpose": "historical_observation_and_return_measurement_only",
        }
