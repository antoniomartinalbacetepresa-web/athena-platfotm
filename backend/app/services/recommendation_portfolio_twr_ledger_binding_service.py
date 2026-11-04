from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Iterable

from app.services.recommendation_portfolio_twr_measurement_service import (
    PortfolioTwrBoundaryInput,
    PortfolioTwrInternalCashEventInput,
    PortfolioTwrMeasurementResult,
    RecommendationPortfolioTwrMeasurementService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PortfolioTwrExternalFlowEventInput:
    event_key: str
    amount: float
    currency: str
    occurred_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class LedgerBoundPortfolioTwrResult:
    measurement_key: str
    core: PortfolioTwrMeasurementResult
    external_flow_events: tuple[dict[str, object], ...]

    def to_api_dict(self) -> dict[str, object]:
        payload = self.core.to_api_dict()
        payload["status"] = "measured_and_bound_to_external_cash_flow_ledger"
        payload["coreMeasurementKey"] = payload["measurementKey"]
        payload["measurementKey"] = self.measurement_key
        payload["externalFlowEvents"] = [dict(item) for item in self.external_flow_events]
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("TWR core result lost policy")
        policy["externalFlowLedgerBinding"] = (
            "every_nonzero_interior_boundary_requires_exact_unique_pit_external_cash_flow_event"
        )
        policy["callerMayOmitKnownExternalFlow"] = False
        policy["callerMayInventExternalFlow"] = False
        return payload


class RecommendationPortfolioTwrLedgerBindingService:
    """Fail-closed gate that binds TWR boundaries to observed ledger cash flows.

    The underlying TWR primitive performs the return mathematics. This gate closes
    the omission/invention risk by requiring a one-to-one match between every
    non-zero interior boundary flow and one explicit external_cash_flow ledger
    event. The resulting measurement hash includes the ledger event identities and
    provenance, so the public research artifact can be tamper-evident end-to-end.
    """

    _ABS_TOLERANCE = 1e-9
    _MAX_EXTERNAL_FLOWS = 1998

    def __init__(self, *, twr_service: RecommendationPortfolioTwrMeasurementService | None = None) -> None:
        self._twr_service = twr_service or RecommendationPortfolioTwrMeasurementService()

    def evaluate(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
        boundaries: Iterable[PortfolioTwrBoundaryInput],
        external_cash_flows: Iterable[PortfolioTwrExternalFlowEventInput],
        internal_cash_events: Iterable[PortfolioTwrInternalCashEventInput] = (),
    ) -> LedgerBoundPortfolioTwrResult:
        start = self._aware_utc(period_start, "period_start")
        end = self._aware_utc(period_end, "period_end")
        cutoff = self._aware_utc(as_of, "as_of")
        if not start < end <= cutoff:
            raise ValueError("ledger-bound TWR requires period_start < period_end <= as_of")
        currency = self._currency(reporting_currency, "reporting_currency")

        boundary_items = tuple(boundaries)
        flow_items = tuple(external_cash_flows)
        if len(flow_items) > self._MAX_EXTERNAL_FLOWS:
            raise ValueError("external cash flow count exceeds supported maximum")

        normalized_flows: list[dict[str, object]] = []
        seen_keys: set[str] = set()
        seen_provenance: set[tuple[str, str]] = set()
        seen_times: set[datetime] = set()
        for index, item in enumerate(flow_items):
            normalized = self._flow(
                item,
                index=index,
                currency=currency,
                start=start,
                end=end,
                cutoff=cutoff,
            )
            key = str(normalized["eventKey"])
            provenance = (str(normalized["source"]), str(normalized["sourceRef"]))
            occurred = datetime.fromisoformat(str(normalized["occurredAt"]))
            if key in seen_keys:
                raise ValueError("external cash flows contain duplicate event_key")
            if provenance in seen_provenance:
                raise ValueError("external cash flows contain duplicate provenance")
            if occurred in seen_times:
                raise ValueError(
                    "multiple external cash flows at one instant require upstream deterministic aggregation"
                )
            seen_keys.add(key)
            seen_provenance.add(provenance)
            seen_times.add(occurred)
            normalized_flows.append(normalized)
        normalized_flows.sort(key=lambda item: (str(item["occurredAt"]), str(item["eventKey"])))

        boundary_flow_by_time: dict[datetime, float] = {}
        if len(boundary_items) < 2:
            raise ValueError("ledger-bound TWR requires at least start/end boundaries")
        for index, boundary in enumerate(boundary_items):
            if not isinstance(boundary, PortfolioTwrBoundaryInput):
                raise ValueError(f"boundaries[{index}] must be PortfolioTwrBoundaryInput")
            observed = self._aware_utc(boundary.observed_at, f"boundaries[{index}].observed_at")
            amount = self._finite(boundary.external_flow_amount, f"boundaries[{index}].external_flow_amount")
            if index in {0, len(boundary_items) - 1}:
                if abs(amount) > self._ABS_TOLERANCE:
                    raise ValueError("period edge boundaries cannot carry ledger external flows")
                continue
            if abs(amount) <= self._ABS_TOLERANCE:
                continue
            if observed in boundary_flow_by_time:
                raise ValueError("duplicate nonzero external-flow boundary timestamp")
            boundary_flow_by_time[observed] = amount

        ledger_flow_by_time = {
            datetime.fromisoformat(str(item["occurredAt"])): float(item["amount"])
            for item in normalized_flows
        }
        if set(boundary_flow_by_time) != set(ledger_flow_by_time):
            missing_boundary = sorted(set(ledger_flow_by_time) - set(boundary_flow_by_time))
            invented_boundary = sorted(set(boundary_flow_by_time) - set(ledger_flow_by_time))
            if missing_boundary:
                raise ValueError("known ledger external cash flow is missing an exact TWR valuation boundary")
            if invented_boundary:
                raise ValueError("TWR boundary contains an external flow absent from the supplied ledger evidence")
            raise ValueError("TWR external-flow boundaries do not match ledger evidence")
        for observed, boundary_amount in boundary_flow_by_time.items():
            ledger_amount = ledger_flow_by_time[observed]
            if not math.isclose(
                boundary_amount,
                ledger_amount,
                rel_tol=0.0,
                abs_tol=self._ABS_TOLERANCE,
            ):
                raise ValueError("TWR boundary external flow amount does not match ledger event amount")

        core = self._twr_service.evaluate(
            portfolio_id=portfolio_id,
            reporting_currency=currency,
            period_start=start,
            period_end=end,
            as_of=cutoff,
            boundaries=boundary_items,
            internal_cash_events=tuple(internal_cash_events),
        )
        if not math.isclose(
            core.external_flow_total,
            sum(float(item["amount"]) for item in normalized_flows),
            rel_tol=0.0,
            abs_tol=self._ABS_TOLERANCE,
        ):
            raise ValueError("TWR core external flow total does not reconcile to ledger events")

        identity = {
            "schema": "athena_portfolio_twr_ledger_binding_v1",
            "coreMeasurementKey": core.measurement_key,
            "externalFlowEvents": normalized_flows,
        }
        measurement_key = hashlib.sha256(self._serialize(identity).encode("utf-8")).hexdigest()
        return LedgerBoundPortfolioTwrResult(
            measurement_key=measurement_key,
            core=core,
            external_flow_events=tuple(normalized_flows),
        )

    def _flow(
        self,
        item: PortfolioTwrExternalFlowEventInput,
        *,
        index: int,
        currency: str,
        start: datetime,
        end: datetime,
        cutoff: datetime,
    ) -> dict[str, object]:
        if not isinstance(item, PortfolioTwrExternalFlowEventInput):
            raise ValueError(f"external_cash_flows[{index}] must be PortfolioTwrExternalFlowEventInput")
        event_key = self._sha256(item.event_key, f"external_cash_flows[{index}].event_key")
        amount = self._finite(item.amount, f"external_cash_flows[{index}].amount")
        if abs(amount) <= self._ABS_TOLERANCE:
            raise ValueError("external_cash_flow event amount must be non-zero")
        event_currency = self._currency(item.currency, f"external_cash_flows[{index}].currency")
        if event_currency != currency:
            raise ValueError("external cash flow currency requires explicit FX conversion evidence")
        occurred = self._aware_utc(item.occurred_at, f"external_cash_flows[{index}].occurred_at")
        available = self._aware_utc(item.available_at, f"external_cash_flows[{index}].available_at")
        if not start < occurred < end:
            raise ValueError("external cash flow must occur strictly inside the TWR period")
        if occurred > available or available > cutoff:
            raise ValueError("external cash flow violates occurred_at <= available_at <= as_of")
        return {
            "eventKey": event_key,
            "eventType": "external_cash_flow",
            "amount": amount,
            "currency": event_currency,
            "occurredAt": occurred.isoformat(),
            "availableAt": available.isoformat(),
            "source": self._text(item.source, f"external_cash_flows[{index}].source"),
            "sourceRef": self._text(item.source_ref, f"external_cash_flows[{index}].source_ref"),
        }

    @staticmethod
    def _serialize(value: object) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("ledger-bound TWR contains non-serializable/non-finite data") from exc

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text

    @classmethod
    def _currency(cls, value: object, field: str) -> str:
        currency = cls._text(value, field).upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError(f"{field} must be a three-letter currency code")
        return currency

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} must be a SHA-256 hexadecimal fingerprint")
        return text

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be finite")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be finite") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)
