from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Iterable


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INTERNAL_CASH_TYPES = frozenset({"cash_dividend", "fee", "tax"})
_TOTAL_VALUE_SCOPE = "total_net_liquidation_value_in_reporting_currency"


@dataclass(frozen=True)
class PortfolioTwrBoundaryInput:
    observed_at: datetime
    available_at: datetime
    pre_flow_value: float
    post_flow_value: float
    external_flow_amount: float
    currency: str
    valuation_scope: str
    valuation_fingerprint: str
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioTwrInternalCashEventInput:
    event_key: str
    event_type: str
    amount: float
    currency: str
    occurred_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioTwrMeasurementResult:
    measurement_key: str
    portfolio_id: str
    reporting_currency: str
    period_start: datetime
    period_end: datetime
    as_of: datetime
    time_weighted_return: float
    segment_returns: tuple[dict[str, object], ...]
    boundaries: tuple[dict[str, object], ...]
    external_flow_total: float
    internal_cash_totals: dict[str, float]
    internal_cash_events: tuple[dict[str, object], ...]

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "portfolio_twr_measurement",
            "status": "measured_from_explicit_total_value_boundaries",
            "measurementKey": self.measurement_key,
            "portfolioId": self.portfolio_id,
            "reportingCurrency": self.reporting_currency,
            "periodStart": self.period_start.isoformat(),
            "periodEnd": self.period_end.isoformat(),
            "asOf": self.as_of.isoformat(),
            "timeWeightedReturn": self.time_weighted_return,
            "segmentReturns": [dict(item) for item in self.segment_returns],
            "boundaries": [dict(item) for item in self.boundaries],
            "externalFlowTotal": self.external_flow_total,
            "internalCashTotals": dict(self.internal_cash_totals),
            "internalCashEvents": [dict(item) for item in self.internal_cash_events],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "valuationScope": _TOTAL_VALUE_SCOPE,
                "externalFlowTreatment": "excluded_by_exact_pre_post_flow_boundary_reconciliation",
                "internalCashTreatment": "included_in_portfolio_value_evolution_not_external_flow",
                "cashDividend": "internal_return_cash_not_external_contribution",
                "fee": "internal_negative_cash_friction",
                "tax": "internal_negative_cash_friction",
                "splitAdjustment": "quantity_only_no_direct_return_contribution",
                "timing": "every_external_flow_requires_an_exact_valuation_boundary",
                "fx": "reporting_currency_only_no_fx_inference",
                "causalAttribution": "not_estimated_from_monetary_events_without_valid_return_denominator",
                "residualAlphaOrSkill": "not_claimed",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationPortfolioTwrMeasurementService:
    """Measure portfolio TWR only from explicit total-value PIT boundaries.

    Each interior boundary represents a valuation immediately before an external
    contribution/withdrawal and immediately after it. The identity
    ``post_flow_value == pre_flow_value + external_flow_amount`` must reconcile
    exactly within numerical tolerance. Segment returns therefore never classify
    external capital as investment performance.

    Dividend, fee and tax events are reported as internal cash evidence. They are
    not converted from currency amounts into percentage contributions here; their
    economic effect is already reflected by total portfolio values. A later
    attribution layer may decompose them only when an independently valid return
    denominator and timing convention are available.
    """

    _ABS_TOLERANCE = 1e-9
    _MAX_BOUNDARIES = 2000
    _MAX_INTERNAL_EVENTS = 10000

    def evaluate(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
        boundaries: Iterable[PortfolioTwrBoundaryInput],
        internal_cash_events: Iterable[PortfolioTwrInternalCashEventInput] = (),
    ) -> PortfolioTwrMeasurementResult:
        portfolio = self._text(portfolio_id, "portfolio_id")
        currency = self._currency(reporting_currency, "reporting_currency")
        start = self._aware_utc(period_start, "period_start")
        end = self._aware_utc(period_end, "period_end")
        cutoff = self._aware_utc(as_of, "as_of")
        if not start < end <= cutoff:
            raise ValueError("TWR requires period_start < period_end <= as_of")

        raw_boundaries = tuple(boundaries)
        if len(raw_boundaries) < 2:
            raise ValueError("TWR requires at least start and end valuation boundaries")
        if len(raw_boundaries) > self._MAX_BOUNDARIES:
            raise ValueError("TWR boundary count exceeds supported maximum")

        normalized_boundaries = tuple(
            self._boundary(item, index=index, currency=currency, cutoff=cutoff)
            for index, item in enumerate(raw_boundaries)
        )
        times = [item["observedAt"] for item in normalized_boundaries]
        if times[0] != start.isoformat() or times[-1] != end.isoformat():
            raise ValueError("first/last TWR boundaries must equal period_start/period_end")
        if any(times[index] >= times[index + 1] for index in range(len(times) - 1)):
            raise ValueError("TWR boundaries must be strictly increasing and unique")

        for edge_index in (0, len(normalized_boundaries) - 1):
            boundary = normalized_boundaries[edge_index]
            if abs(float(boundary["externalFlowAmount"])) > self._ABS_TOLERANCE:
                raise ValueError("period start/end TWR boundaries cannot carry external flows")
            if not math.isclose(
                float(boundary["preFlowValue"]),
                float(boundary["postFlowValue"]),
                rel_tol=0.0,
                abs_tol=self._ABS_TOLERANCE,
            ):
                raise ValueError("period start/end TWR boundary values must match")

        segments: list[dict[str, object]] = []
        linked_growth = 1.0
        for index in range(len(normalized_boundaries) - 1):
            opening = normalized_boundaries[index]
            closing = normalized_boundaries[index + 1]
            denominator = float(opening["postFlowValue"])
            numerator = float(closing["preFlowValue"])
            if denominator <= 0.0:
                raise ValueError("TWR segment opening total value must be positive")
            segment_return = self._finite(numerator / denominator - 1.0, "segment_return")
            if segment_return < -1.0 - self._ABS_TOLERANCE:
                raise ValueError("TWR segment return cannot be below -100%")
            linked_growth = self._finite(linked_growth * (1.0 + segment_return), "linked_growth")
            segments.append(
                {
                    "segmentIndex": index,
                    "periodStart": opening["observedAt"],
                    "periodEnd": closing["observedAt"],
                    "openingPostFlowValue": denominator,
                    "closingPreFlowValue": numerator,
                    "return": segment_return,
                    "openingValuationFingerprint": opening["valuationFingerprint"],
                    "closingValuationFingerprint": closing["valuationFingerprint"],
                }
            )
        twr = self._finite(linked_growth - 1.0, "time_weighted_return")

        raw_internal = tuple(internal_cash_events)
        if len(raw_internal) > self._MAX_INTERNAL_EVENTS:
            raise ValueError("internal cash event count exceeds supported maximum")
        normalized_internal: list[dict[str, object]] = []
        seen_event_keys: set[str] = set()
        seen_provenance: set[tuple[str, str]] = set()
        totals = {event_type: 0.0 for event_type in sorted(_INTERNAL_CASH_TYPES)}
        for index, item in enumerate(raw_internal):
            normalized = self._internal_event(
                item,
                index=index,
                currency=currency,
                start=start,
                end=end,
                cutoff=cutoff,
            )
            key = str(normalized["eventKey"])
            provenance = (str(normalized["source"]), str(normalized["sourceRef"]))
            if key in seen_event_keys:
                raise ValueError("internal cash events contain duplicate event_key")
            if provenance in seen_provenance:
                raise ValueError("internal cash events contain duplicate provenance")
            seen_event_keys.add(key)
            seen_provenance.add(provenance)
            event_type = str(normalized["eventType"])
            totals[event_type] = self._finite(
                totals[event_type] + float(normalized["amount"]),
                f"internal_cash_total:{event_type}",
            )
            normalized_internal.append(normalized)
        normalized_internal.sort(
            key=lambda item: (str(item["occurredAt"]), str(item["eventType"]), str(item["eventKey"]))
        )

        external_total = self._finite(
            sum(float(item["externalFlowAmount"]) for item in normalized_boundaries[1:-1]),
            "external_flow_total",
        )
        identity = {
            "schema": "athena_portfolio_twr_measurement_v1",
            "portfolioId": portfolio,
            "reportingCurrency": currency,
            "periodStart": start.isoformat(),
            "periodEnd": end.isoformat(),
            "asOf": cutoff.isoformat(),
            "boundaries": list(normalized_boundaries),
            "internalCashEvents": normalized_internal,
            "segmentReturns": segments,
            "timeWeightedReturn": format(twr, ".17g"),
        }
        measurement_key = hashlib.sha256(self._serialize(identity).encode("utf-8")).hexdigest()
        return PortfolioTwrMeasurementResult(
            measurement_key=measurement_key,
            portfolio_id=portfolio,
            reporting_currency=currency,
            period_start=start,
            period_end=end,
            as_of=cutoff,
            time_weighted_return=twr,
            segment_returns=tuple(segments),
            boundaries=normalized_boundaries,
            external_flow_total=external_total,
            internal_cash_totals=totals,
            internal_cash_events=tuple(normalized_internal),
        )

    def _boundary(
        self,
        item: PortfolioTwrBoundaryInput,
        *,
        index: int,
        currency: str,
        cutoff: datetime,
    ) -> dict[str, object]:
        if not isinstance(item, PortfolioTwrBoundaryInput):
            raise ValueError(f"boundaries[{index}] must be PortfolioTwrBoundaryInput")
        observed = self._aware_utc(item.observed_at, f"boundaries[{index}].observed_at")
        available = self._aware_utc(item.available_at, f"boundaries[{index}].available_at")
        if observed > available or available > cutoff:
            raise ValueError("TWR boundary violates observed_at <= available_at <= as_of")
        item_currency = self._currency(item.currency, f"boundaries[{index}].currency")
        if item_currency != currency:
            raise ValueError("TWR boundary currency requires explicit FX conversion evidence")
        scope = self._text(item.valuation_scope, f"boundaries[{index}].valuation_scope")
        if scope != _TOTAL_VALUE_SCOPE:
            raise ValueError("TWR requires total net liquidation value; partial position valuation is insufficient")
        fingerprint = self._sha256(item.valuation_fingerprint, f"boundaries[{index}].valuation_fingerprint")
        pre = self._nonnegative_finite(item.pre_flow_value, f"boundaries[{index}].pre_flow_value")
        post = self._nonnegative_finite(item.post_flow_value, f"boundaries[{index}].post_flow_value")
        flow = self._finite(item.external_flow_amount, f"boundaries[{index}].external_flow_amount")
        expected_post = self._finite(pre + flow, f"boundaries[{index}].reconciled_post_flow_value")
        if expected_post < -self._ABS_TOLERANCE:
            raise ValueError("external flow would make total portfolio value negative")
        if not math.isclose(post, expected_post, rel_tol=0.0, abs_tol=self._ABS_TOLERANCE):
            raise ValueError("TWR boundary does not reconcile post_flow_value = pre_flow_value + external_flow_amount")
        return {
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "preFlowValue": pre,
            "postFlowValue": post,
            "externalFlowAmount": flow,
            "currency": item_currency,
            "valuationScope": scope,
            "valuationFingerprint": fingerprint,
            "source": self._text(item.source, f"boundaries[{index}].source"),
            "sourceRef": self._text(item.source_ref, f"boundaries[{index}].source_ref"),
        }

    def _internal_event(
        self,
        item: PortfolioTwrInternalCashEventInput,
        *,
        index: int,
        currency: str,
        start: datetime,
        end: datetime,
        cutoff: datetime,
    ) -> dict[str, object]:
        if not isinstance(item, PortfolioTwrInternalCashEventInput):
            raise ValueError(f"internal_cash_events[{index}] must be PortfolioTwrInternalCashEventInput")
        event_key = self._sha256(item.event_key, f"internal_cash_events[{index}].event_key")
        event_type = self._text(item.event_type, f"internal_cash_events[{index}].event_type").lower()
        if event_type not in _INTERNAL_CASH_TYPES:
            raise ValueError("TWR internal cash event type must be cash_dividend, fee or tax")
        event_currency = self._currency(item.currency, f"internal_cash_events[{index}].currency")
        if event_currency != currency:
            raise ValueError("internal cash event currency requires explicit FX conversion evidence")
        occurred = self._aware_utc(item.occurred_at, f"internal_cash_events[{index}].occurred_at")
        available = self._aware_utc(item.available_at, f"internal_cash_events[{index}].available_at")
        if not start < occurred <= end:
            raise ValueError("internal cash event must occur inside the measured period")
        if occurred > available or available > cutoff:
            raise ValueError("internal cash event violates occurred_at <= available_at <= as_of")
        amount = self._finite(item.amount, f"internal_cash_events[{index}].amount")
        if event_type == "cash_dividend" and amount == 0.0:
            raise ValueError("cash_dividend amount must be non-zero")
        if event_type in {"fee", "tax"} and amount >= 0.0:
            raise ValueError(f"{event_type} amount must be negative")
        return {
            "eventKey": event_key,
            "eventType": event_type,
            "amount": amount,
            "currency": event_currency,
            "occurredAt": occurred.isoformat(),
            "availableAt": available.isoformat(),
            "source": self._text(item.source, f"internal_cash_events[{index}].source"),
            "sourceRef": self._text(item.source_ref, f"internal_cash_events[{index}].source_ref"),
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
            raise ValueError("TWR measurement contains non-serializable/non-finite data") from exc

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

    @classmethod
    def _nonnegative_finite(cls, value: object, field: str) -> float:
        numeric = cls._finite(value, field)
        if numeric < 0.0:
            raise ValueError(f"{field} cannot be negative")
        return numeric

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)
