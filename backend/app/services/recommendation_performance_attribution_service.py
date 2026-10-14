from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
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
    instrument_currency: str
    reporting_currency: str
    fx_pair: str
    benchmark_id: str
    period_start: datetime
    period_end: datetime
    total_return: AttributionEvidence
    market_contribution: AttributionEvidence
    fx_contribution: AttributionEvidence
    factor_contributions: tuple[FactorContributionEvidence, ...]


@dataclass(frozen=True)
class RecommendationPerformanceAttributionResult:
    attribution_key: str
    instrument_id: str
    symbol: str
    instrument_currency: str
    reporting_currency: str
    fx_pair: str
    benchmark_id: str
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
            "attributionKey": self.attribution_key,
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "benchmarkId": self.benchmark_id,
            "currency": {
                "instrumentCurrency": self.instrument_currency,
                "reportingCurrency": self.reporting_currency,
                "fxPair": self.fx_pair,
                "conversionRequired": self.instrument_currency != self.reporting_currency,
            },
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
                "fx": "explicit_currency_pair_bound_fail_closed",
                "identity": "deterministic_sha256_attribution_key",
                "identityBinding": "numeric_values_plus_pit_provenance_plus_period_and_instrument",
                "benchmark": "explicit_market_contribution_identity",
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

    @classmethod
    def _currency(cls, value: str, field: str) -> str:
        cleaned = cls._text(value, field).upper()
        if len(cleaned) != 3 or not cleaned.isascii() or not cleaned.isalpha():
            raise ValueError(f"{field} must be a three-letter currency code")
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

    @staticmethod
    def _number_token(value: float) -> str:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("attribution identity value must be finite")
        return format(numeric, ".17g")

    @classmethod
    def _attribution_key(
        cls,
        *,
        instrument_id: str,
        symbol: str,
        benchmark_id: str,
        instrument_currency: str,
        reporting_currency: str,
        fx_pair: str,
        as_of: datetime,
        period_start: datetime,
        period_end: datetime,
        total_return: float,
        market_contribution: float,
        fx_contribution: float,
        factor_values: dict[str, float],
        evidence: dict[str, object],
    ) -> str:
        factor_meta = evidence["factorContributions"]
        assert isinstance(factor_meta, dict)
        factor_tokens = []
        for name in sorted(factor_meta):
            meta = factor_meta[name]
            assert isinstance(meta, dict)
            factor_tokens.append(
                f"{name}:{cls._number_token(factor_values[name])}:{meta['availableAt']}:{meta['source']}:{meta['sourceRef']}"
            )

        tokens = [
            "performance_attribution_v3",
            instrument_id,
            symbol,
            benchmark_id,
            instrument_currency,
            reporting_currency,
            fx_pair,
            as_of.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
        ]
        numeric_values = {
            "totalReturn": total_return,
            "marketContribution": market_contribution,
            "fxContribution": fx_contribution,
        }
        for key in ("totalReturn", "marketContribution", "fxContribution"):
            meta = evidence[key]
            assert isinstance(meta, dict)
            tokens.append(
                f"{key}:{cls._number_token(numeric_values[key])}:{meta['availableAt']}:{meta['source']}:{meta['sourceRef']}"
            )
        tokens.extend(factor_tokens)
        return hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()

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
        benchmark_id = self._text(item.benchmark_id, "benchmark_id")
        instrument_currency = self._currency(item.instrument_currency, "instrument_currency")
        reporting_currency = self._currency(item.reporting_currency, "reporting_currency")
        fx_pair = self._text(item.fx_pair, "fx_pair").upper()
        expected_fx_pair = f"{instrument_currency}/{reporting_currency}"
        if fx_pair != expected_fx_pair:
            raise ValueError(f"fx_pair must be {expected_fx_pair}")

        total_return, total_meta = self._normalize_evidence(
            item.total_return, field="total_return", as_of=as_of_utc
        )
        market, market_meta = self._normalize_evidence(
            item.market_contribution, field="market_contribution", as_of=as_of_utc
        )
        fx, fx_meta = self._normalize_evidence(
            item.fx_contribution, field="fx_contribution", as_of=as_of_utc
        )
        if instrument_currency == reporting_currency and not math.isclose(
            fx, 0.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("fx_contribution must be zero when no currency conversion is required")

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

        evidence = {
            "totalReturn": total_meta,
            "marketContribution": market_meta,
            "fxContribution": fx_meta,
            "factorContributions": factor_meta,
        }
        attribution_key = self._attribution_key(
            instrument_id=instrument_id,
            symbol=symbol,
            benchmark_id=benchmark_id,
            instrument_currency=instrument_currency,
            reporting_currency=reporting_currency,
            fx_pair=fx_pair,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            total_return=total_return,
            market_contribution=market,
            fx_contribution=fx,
            factor_values=factor_values,
            evidence=evidence,
        )

        return RecommendationPerformanceAttributionResult(
            attribution_key=attribution_key,
            instrument_id=instrument_id,
            symbol=symbol,
            instrument_currency=instrument_currency,
            reporting_currency=reporting_currency,
            fx_pair=fx_pair,
            benchmark_id=benchmark_id,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            total_return=total_return,
            market_contribution=market,
            fx_contribution=fx,
            factor_contributions=factor_values,
            explained_return=explained,
            residual_return=residual,
            evidence=evidence,
        )
