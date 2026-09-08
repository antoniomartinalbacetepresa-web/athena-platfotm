from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math


@dataclass(frozen=True)
class PortfolioValueEvidence:
    value: float
    observed_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioCashFlowEvidence:
    amount: float
    occurred_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioTwrSegment:
    start_at: datetime
    end_at: datetime
    beginning_value: PortfolioValueEvidence
    ending_value_before_flow: PortfolioValueEvidence
    external_flow_after_end: PortfolioCashFlowEvidence | None = None


@dataclass(frozen=True)
class RecommendationPortfolioTimeWeightedReturnInput:
    portfolio_id: str
    reporting_currency: str
    period_start: datetime
    period_end: datetime
    segments: tuple[PortfolioTwrSegment, ...]


@dataclass(frozen=True)
class RecommendationPortfolioTimeWeightedReturnResult:
    return_key: str
    portfolio_id: str
    reporting_currency: str
    as_of: datetime
    period_start: datetime
    period_end: datetime
    time_weighted_return: float
    segment_returns: tuple[dict[str, object], ...]
    external_flow_count: int
    net_external_flow: float

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "portfolio_time_weighted_return",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "portfolioReturnKey": self.return_key,
            "portfolioId": self.portfolio_id,
            "reportingCurrency": self.reporting_currency,
            "asOf": self.as_of.isoformat(),
            "periodStart": self.period_start.isoformat(),
            "periodEnd": self.period_end.isoformat(),
            "timeWeightedReturn": self.time_weighted_return,
            "externalFlowCount": self.external_flow_count,
            "netExternalFlow": self.net_external_flow,
            "segments": [dict(item) for item in self.segment_returns],
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "returnMethod": "time_weighted_return_geometric_chain",
                "externalFlows": "boundary_flows_explicit_and_reconciled",
                "internalTrades": "not_external_flows_valuation_boundaries_required",
                "cashInference": "forbidden",
                "valuationBoundary": "pre_flow_end_and_post_flow_next_start_must_reconcile",
                "temporal": "observed_at_lte_available_at_lte_as_of",
                "identity": "deterministic_sha256_portfolio_return_key",
                "purpose": "historical_measurement_diagnostic_only",
            },
        }


class RecommendationPortfolioTimeWeightedReturnService:
    _RECONCILIATION_ABS_TOLERANCE = 1e-8
    _RECONCILIATION_REL_TOLERANCE = 1e-12

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

    def _value_evidence(
        self,
        evidence: PortfolioValueEvidence,
        *,
        field: str,
        expected_observed_at: datetime,
        as_of: datetime,
    ) -> tuple[float, dict[str, str]]:
        value = self._finite(evidence.value, f"{field}.value")
        if value <= 0.0:
            raise ValueError(f"{field}.value must be positive")
        observed_at = self._aware_utc(evidence.observed_at, f"{field}.observed_at")
        available_at = self._aware_utc(evidence.available_at, f"{field}.available_at")
        if observed_at != expected_observed_at:
            raise ValueError(f"{field}.observed_at must equal its segment boundary")
        if observed_at > available_at or available_at > as_of:
            raise ValueError(f"{field} violates observed_at <= available_at <= as_of")
        return value, {
            "observedAt": observed_at.isoformat(),
            "availableAt": available_at.isoformat(),
            "source": self._text(evidence.source, f"{field}.source"),
            "sourceRef": self._text(evidence.source_ref, f"{field}.source_ref"),
        }

    def _flow_evidence(
        self,
        evidence: PortfolioCashFlowEvidence,
        *,
        field: str,
        expected_occurred_at: datetime,
        as_of: datetime,
    ) -> tuple[float, dict[str, str]]:
        amount = self._finite(evidence.amount, f"{field}.amount")
        if amount == 0.0:
            raise ValueError(f"{field}.amount must be non-zero when a flow is supplied")
        occurred_at = self._aware_utc(evidence.occurred_at, f"{field}.occurred_at")
        available_at = self._aware_utc(evidence.available_at, f"{field}.available_at")
        if occurred_at != expected_occurred_at:
            raise ValueError(f"{field}.occurred_at must equal the segment end boundary")
        if occurred_at > available_at or available_at > as_of:
            raise ValueError(f"{field} violates occurred_at <= available_at <= as_of")
        return amount, {
            "occurredAt": occurred_at.isoformat(),
            "availableAt": available_at.isoformat(),
            "source": self._text(evidence.source, f"{field}.source"),
            "sourceRef": self._text(evidence.source_ref, f"{field}.source_ref"),
        }

    @staticmethod
    def _return_key(
        *,
        portfolio_id: str,
        reporting_currency: str,
        as_of: datetime,
        period_start: datetime,
        period_end: datetime,
        segments: tuple[dict[str, object], ...],
    ) -> str:
        tokens = [
            "portfolio_time_weighted_return_v1",
            portfolio_id,
            reporting_currency,
            as_of.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
        ]
        for segment in segments:
            beginning = segment["beginningValueEvidence"]
            ending = segment["endingValueEvidence"]
            assert isinstance(beginning, dict) and isinstance(ending, dict)
            tokens.extend(
                [
                    str(segment["startAt"]),
                    str(segment["endAt"]),
                    format(float(segment["beginningValue"]), ".17g"),
                    format(float(segment["endingValueBeforeFlow"]), ".17g"),
                    str(beginning["availableAt"]),
                    str(beginning["source"]),
                    str(beginning["sourceRef"]),
                    str(ending["availableAt"]),
                    str(ending["source"]),
                    str(ending["sourceRef"]),
                ]
            )
            flow = segment.get("externalFlowAfterEnd")
            if isinstance(flow, dict):
                evidence = flow["evidence"]
                assert isinstance(evidence, dict)
                tokens.extend(
                    [
                        format(float(flow["amount"]), ".17g"),
                        str(evidence["availableAt"]),
                        str(evidence["source"]),
                        str(evidence["sourceRef"]),
                    ]
                )
            else:
                tokens.append("no_external_flow")
        return hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()

    def evaluate(
        self,
        *,
        as_of: datetime,
        item: RecommendationPortfolioTimeWeightedReturnInput,
    ) -> RecommendationPortfolioTimeWeightedReturnResult:
        as_of_utc = self._aware_utc(as_of, "as_of")
        period_start = self._aware_utc(item.period_start, "period_start")
        period_end = self._aware_utc(item.period_end, "period_end")
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        if period_end > as_of_utc:
            raise ValueError("period_end cannot be after as_of")
        portfolio_id = self._text(item.portfolio_id, "portfolio_id")
        reporting_currency = self._currency(item.reporting_currency, "reporting_currency")
        if not item.segments:
            raise ValueError("segments are required")

        payloads: list[dict[str, object]] = []
        chain = 1.0
        flow_count = 0
        net_flow = 0.0
        previous_end: datetime | None = None
        previous_end_value: float | None = None
        previous_flow = 0.0

        for index, segment in enumerate(item.segments):
            start_at = self._aware_utc(segment.start_at, f"segments[{index}].start_at")
            end_at = self._aware_utc(segment.end_at, f"segments[{index}].end_at")
            if end_at <= start_at:
                raise ValueError("each segment end_at must be after start_at")
            if index == 0 and start_at != period_start:
                raise ValueError("first segment must start at period_start")
            if previous_end is not None and start_at != previous_end:
                raise ValueError("segments must be contiguous and ordered")
            if end_at > period_end:
                raise ValueError("segment cannot end after period_end")

            beginning_value, beginning_meta = self._value_evidence(
                segment.beginning_value,
                field=f"segments[{index}].beginning_value",
                expected_observed_at=start_at,
                as_of=as_of_utc,
            )
            ending_value, ending_meta = self._value_evidence(
                segment.ending_value_before_flow,
                field=f"segments[{index}].ending_value_before_flow",
                expected_observed_at=end_at,
                as_of=as_of_utc,
            )
            if previous_end_value is not None:
                expected_beginning = previous_end_value + previous_flow
                if expected_beginning <= 0.0 or not math.isclose(
                    beginning_value,
                    expected_beginning,
                    rel_tol=self._RECONCILIATION_REL_TOLERANCE,
                    abs_tol=self._RECONCILIATION_ABS_TOLERANCE,
                ):
                    raise ValueError("post-flow beginning value does not reconcile to prior boundary")

            segment_return = ending_value / beginning_value - 1.0
            self._finite(segment_return, f"segments[{index}].return")
            chain *= 1.0 + segment_return
            self._finite(chain, "geometric return chain")

            flow_amount = 0.0
            flow_payload: dict[str, object] | None = None
            if segment.external_flow_after_end is not None:
                if end_at == period_end:
                    raise ValueError("external flow after final period_end is outside the measurement period")
                flow_amount, flow_meta = self._flow_evidence(
                    segment.external_flow_after_end,
                    field=f"segments[{index}].external_flow_after_end",
                    expected_occurred_at=end_at,
                    as_of=as_of_utc,
                )
                if ending_value + flow_amount <= 0.0:
                    raise ValueError("external flow would make post-flow portfolio value non-positive")
                flow_count += 1
                net_flow += flow_amount
                self._finite(net_flow, "net_external_flow")
                flow_payload = {"amount": flow_amount, "evidence": flow_meta}

            payloads.append(
                {
                    "startAt": start_at.isoformat(),
                    "endAt": end_at.isoformat(),
                    "beginningValue": beginning_value,
                    "endingValueBeforeFlow": ending_value,
                    "segmentReturn": segment_return,
                    "beginningValueEvidence": beginning_meta,
                    "endingValueEvidence": ending_meta,
                    "externalFlowAfterEnd": flow_payload,
                }
            )
            previous_end = end_at
            previous_end_value = ending_value
            previous_flow = flow_amount

        if previous_end != period_end:
            raise ValueError("final segment must end at period_end")
        time_weighted_return = chain - 1.0
        self._finite(time_weighted_return, "time_weighted_return")
        segment_tuple = tuple(payloads)
        key = self._return_key(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            segments=segment_tuple,
        )
        return RecommendationPortfolioTimeWeightedReturnResult(
            return_key=key,
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            time_weighted_return=time_weighted_return,
            segment_returns=segment_tuple,
            external_flow_count=flow_count,
            net_external_flow=net_flow,
        )
