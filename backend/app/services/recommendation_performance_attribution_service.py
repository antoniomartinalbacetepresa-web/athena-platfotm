from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class AttributionEvidence:
    value: float
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class FactorContributionEvidence:
    factor: str
    contribution: float
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class RecommendationPerformanceAttributionInput:
    instrument_id: str
    symbol: str
    period_start: datetime
    period_end: datetime
    total_return: AttributionEvidence
    market_contribution: AttributionEvidence
    fx_contribution: AttributionEvidence
    factor_contributions: tuple[FactorContributionEvidence, ...]


@dataclass(frozen=True)
class RecommendationPerformanceAttributionResult:
    instrument_id: str
    symbol: str
    as_of: datetime
    period_start: datetime
    period_end: datetime
    total_return: float
    market_contribution: float
    fx_contribution: float
    factor_contributions: dict[str, float]
    explained_return: float
    residual_return: float
    evidence: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "performance_attribution",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "asOf": self.as_of.isoformat(),
            "periodStart": self.period_start.isoformat(),
            "periodEnd": self.period_end.isoformat(),
            "totalReturn": self.total_return,
            "marketContribution": self.market_contribution,
            "fxContribution": self.fx_contribution,
            "factorContributions": dict(self.factor_contributions),
            "explainedReturn": self.explained_return,
            "residualReturn": self.residual_return,
            "evidence": self.evidence,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "causalClaim": "forbidden_arithmetic_attribution_only",
                "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                "fx": "explicit_not_silently_neutralized",
                "temporal": "all_evidence_available_at_must_be_lte_as_of",
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationPerformanceAttributionService:
    _ALLOWED_FACTORS = {
        "market",
        "size",
        "value",
        "momentum",
        "quality",
        "low_volatility",
        "rates",
    }

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _finite(value: float, field: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    @staticmethod
    def _text(value: str, field: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"{field} is required")
        return cleaned

    def _normalize_evidence(
        self,
        evidence: AttributionEvidence,
        *,
        field: str,
        as_of: datetime,
    ) -> tuple[float, dict[str, str]]:
        value = self._finite(evidence.value, field)
        available_at = self._aware_utc(evidence.available_at, f"{field}.available_at")
        if available_at > as_of:
            raise ValueError(f"{field} evidence is not PIT at as_of")
        source = self._text(evidence.source, f"{field}.source")
        source_ref = self._text(evidence.source_ref, f"{field}.source_ref")
        return value, {
            "availableAt": available_at.isoformat(),
            "source": source,
            "sourceRef": source_ref,
        }

    def evaluate(
        self,
        *,
        as_of: datetime,
        item: RecommendationPerformanceAttributionInput,
    ) -> RecommendationPerformanceAttributionResult:
        as_of_utc = self._aware_utc(as_of, "as_of")
        period_start = self._aware_utc(item.period_start, "period_start")
        period_end = self._aware_utc(item.period_end, "period_end")
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        if period_end > as_of_utc:
            raise ValueError("period_end cannot be after as_of")

        instrument_id = self._text(item.instrument_id, "instrument_id")
        symbol = self._text(item.symbol, "symbol").upper()

        total_return, total_meta = self._normalize_evidence(
            item.total_return, field="total_return", as_of=as_of_utc
        )
        market, market_meta = self._normalize_evidence(
            item.market_contribution, field="market_contribution", as_of=as_of_utc
        )
        fx, fx_meta = self._normalize_evidence(
            item.fx_contribution, field="fx_contribution", as_of=as_of_utc
        )

        factor_values: dict[str, float] = {}
        factor_meta: dict[str, object] = {}
        for factor in item.factor_contributions:
            name = self._text(factor.factor, "factor").lower()
            if name not in self._ALLOWED_FACTORS:
                raise ValueError(f"unsupported factor: {name}")
            if name == "market":
                raise ValueError("market factor must use market_contribution")
            if name in factor_values:
                raise ValueError(f"duplicate factor: {name}")
            value = self._finite(factor.contribution, f"factor[{name}].contribution")
            available_at = self._aware_utc(
                factor.available_at, f"factor[{name}].available_at"
            )
            if available_at > as_of_utc:
                raise ValueError(f"factor[{name}] evidence is not PIT at as_of")
            factor_values[name] = value
            factor_meta[name] = {
                "availableAt": available_at.isoformat(),
                "source": self._text(factor.source, f"factor[{name}].source"),
                "sourceRef": self._text(
                    factor.source_ref, f"factor[{name}].source_ref"
                ),
            }

        explained = market + fx + sum(factor_values.values())
        residual = total_return - explained
        if not math.isfinite(explained) or not math.isfinite(residual):
            raise ValueError("attribution result must be finite")

        return RecommendationPerformanceAttributionResult(
            instrument_id=instrument_id,
            symbol=symbol,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            total_return=total_return,
            market_contribution=market,
            fx_contribution=fx,
            factor_contributions=factor_values,
            explained_return=explained,
            residual_return=residual,
            evidence={
                "totalReturn": total_meta,
                "marketContribution": market_meta,
                "fxContribution": fx_meta,
                "factorContributions": factor_meta,
            },
        )
