from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math

from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)


@dataclass(frozen=True)
class PortfolioAttributionConstituent:
    weight: AttributionEvidence
    attribution: RecommendationPerformanceAttributionInput


@dataclass(frozen=True)
class RecommendationPortfolioPerformanceAttributionInput:
    portfolio_id: str
    benchmark_id: str
    reporting_currency: str
    period_start: datetime
    period_end: datetime
    observed_portfolio_return: AttributionEvidence
    constituents: tuple[PortfolioAttributionConstituent, ...]


@dataclass(frozen=True)
class RecommendationPortfolioPerformanceAttributionResult:
    portfolio_attribution_key: str
    portfolio_id: str
    benchmark_id: str
    reporting_currency: str
    as_of: datetime
    period_start: datetime
    period_end: datetime
    observed_portfolio_return: float
    reconstructed_portfolio_return: float
    reconciliation_error: float
    market_contribution: float
    fx_contribution: float
    factor_contributions: dict[str, float]
    explained_return: float
    residual_return: float
    constituents: tuple[dict[str, object], ...]
    evidence: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "portfolio_performance_attribution",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "portfolioAttributionKey": self.portfolio_attribution_key,
            "portfolioId": self.portfolio_id,
            "benchmarkId": self.benchmark_id,
            "reportingCurrency": self.reporting_currency,
            "asOf": self.as_of.isoformat(),
            "periodStart": self.period_start.isoformat(),
            "periodEnd": self.period_end.isoformat(),
            "observedPortfolioReturn": self.observed_portfolio_return,
            "reconstructedPortfolioReturn": self.reconstructed_portfolio_return,
            "reconciliationError": self.reconciliation_error,
            "marketContribution": self.market_contribution,
            "fxContribution": self.fx_contribution,
            "factorContributions": dict(self.factor_contributions),
            "explainedReturn": self.explained_return,
            "residualReturn": self.residual_return,
            "constituents": [dict(item) for item in self.constituents],
            "evidence": self.evidence,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "causalClaim": "forbidden_arithmetic_attribution_only",
                "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                "weighting": "historical_beginning_weights_diagnostic_only",
                "cashFlows": "unsupported_fail_closed",
                "fx": "child_attributions_explicit_currency_pair_bound",
                "identity": "deterministic_sha256_portfolio_attribution_key",
                "benchmark": "single_explicit_benchmark_required",
                "temporal": "weights_available_at_must_be_lte_period_start",
                "reconciliation": "observed_return_must_match_weighted_constituent_returns",
            },
        }


class RecommendationPortfolioPerformanceAttributionService:
    _WEIGHT_TOLERANCE = 1e-9
    _RECONCILIATION_TOLERANCE = 1e-9

    def __init__(
        self,
        *,
        attribution_service: RecommendationPerformanceAttributionService | None = None,
    ) -> None:
        self._attribution_service = attribution_service or RecommendationPerformanceAttributionService()

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

    def _evidence(
        self,
        evidence: AttributionEvidence,
        *,
        field: str,
        cutoff: datetime,
    ) -> tuple[float, dict[str, str]]:
        value = self._finite(evidence.value, field)
        available_at = self._aware_utc(evidence.available_at, f"{field}.available_at")
        if available_at > cutoff:
            raise ValueError(f"{field} evidence is not PIT at cutoff")
        source = self._text(evidence.source, f"{field}.source")
        source_ref = self._text(evidence.source_ref, f"{field}.source_ref")
        return value, {
            "availableAt": available_at.isoformat(),
            "source": source,
            "sourceRef": source_ref,
        }

    @staticmethod
    def _portfolio_key(
        *,
        portfolio_id: str,
        benchmark_id: str,
        reporting_currency: str,
        as_of: datetime,
        period_start: datetime,
        period_end: datetime,
        observed_meta: dict[str, str],
        constituents: tuple[dict[str, object], ...],
    ) -> str:
        child_tokens = []
        for child in sorted(constituents, key=lambda item: str(item["instrumentId"])):
            weight_meta = child["weightEvidence"]
            assert isinstance(weight_meta, dict)
            child_tokens.append(
                ":".join(
                    [
                        str(child["instrumentId"]),
                        str(child["attributionKey"]),
                        format(float(child["weight"]), ".17g"),
                        str(weight_meta["availableAt"]),
                        str(weight_meta["source"]),
                        str(weight_meta["sourceRef"]),
                    ]
                )
            )
        tokens = [
            "portfolio_performance_attribution_v1",
            portfolio_id,
            benchmark_id,
            reporting_currency,
            as_of.isoformat(),
            period_start.isoformat(),
            period_end.isoformat(),
            f"observed:{observed_meta['availableAt']}:{observed_meta['source']}:{observed_meta['sourceRef']}",
            *child_tokens,
        ]
        return hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()

    def evaluate(
        self,
        *,
        as_of: datetime,
        item: RecommendationPortfolioPerformanceAttributionInput,
    ) -> RecommendationPortfolioPerformanceAttributionResult:
        as_of_utc = self._aware_utc(as_of, "as_of")
        period_start = self._aware_utc(item.period_start, "period_start")
        period_end = self._aware_utc(item.period_end, "period_end")
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        if period_end > as_of_utc:
            raise ValueError("period_end cannot be after as_of")

        portfolio_id = self._text(item.portfolio_id, "portfolio_id")
        benchmark_id = self._text(item.benchmark_id, "benchmark_id")
        reporting_currency = self._currency(item.reporting_currency, "reporting_currency")
        if not item.constituents:
            raise ValueError("constituents are required")

        observed_return, observed_meta = self._evidence(
            item.observed_portfolio_return,
            field="observed_portfolio_return",
            cutoff=as_of_utc,
        )

        seen_instruments: set[str] = set()
        seen_keys: set[str] = set()
        child_payloads: list[dict[str, object]] = []
        weight_sum = 0.0
        reconstructed = 0.0
        market = 0.0
        fx = 0.0
        factors: dict[str, float] = {}

        for index, constituent in enumerate(item.constituents):
            weight, weight_meta = self._evidence(
                constituent.weight,
                field=f"constituents[{index}].weight",
                cutoff=period_start,
            )
            child = self._attribution_service.evaluate(as_of=as_of_utc, item=constituent.attribution)
            if child.period_start != period_start or child.period_end != period_end:
                raise ValueError("all child attributions must use the portfolio period")
            if child.benchmark_id != benchmark_id:
                raise ValueError("all child attributions must use benchmark_id")
            if child.reporting_currency != reporting_currency:
                raise ValueError("all child attributions must use reporting_currency")
            if child.instrument_id in seen_instruments:
                raise ValueError("duplicate instrument_id in portfolio attribution")
            if child.attribution_key in seen_keys:
                raise ValueError("duplicate attribution_key in portfolio attribution")
            seen_instruments.add(child.instrument_id)
            seen_keys.add(child.attribution_key)

            weight_sum += weight
            reconstructed += weight * child.total_return
            market += weight * child.market_contribution
            fx += weight * child.fx_contribution
            for name, contribution in child.factor_contributions.items():
                factors[name] = factors.get(name, 0.0) + weight * contribution

            child_payloads.append(
                {
                    "instrumentId": child.instrument_id,
                    "symbol": child.symbol,
                    "attributionKey": child.attribution_key,
                    "instrumentCurrency": child.instrument_currency,
                    "reportingCurrency": child.reporting_currency,
                    "fxPair": child.fx_pair,
                    "weight": weight,
                    "weightEvidence": weight_meta,
                    "totalReturn": child.total_return,
                }
            )

        if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=self._WEIGHT_TOLERANCE):
            raise ValueError("historical constituent weights must sum to 1.0")

        reconciliation_error = observed_return - reconstructed
        if not math.isclose(
            observed_return,
            reconstructed,
            rel_tol=0.0,
            abs_tol=self._RECONCILIATION_TOLERANCE,
        ):
            raise ValueError("observed portfolio return does not reconcile to weighted constituent returns")

        explained = market + fx + sum(factors.values())
        residual = observed_return - explained
        for field, value in (
            ("reconstructed_portfolio_return", reconstructed),
            ("reconciliation_error", reconciliation_error),
            ("market_contribution", market),
            ("fx_contribution", fx),
            ("explained_return", explained),
            ("residual_return", residual),
        ):
            self._finite(value, field)

        child_tuple = tuple(child_payloads)
        key = self._portfolio_key(
            portfolio_id=portfolio_id,
            benchmark_id=benchmark_id,
            reporting_currency=reporting_currency,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            observed_meta=observed_meta,
            constituents=child_tuple,
        )
        return RecommendationPortfolioPerformanceAttributionResult(
            portfolio_attribution_key=key,
            portfolio_id=portfolio_id,
            benchmark_id=benchmark_id,
            reporting_currency=reporting_currency,
            as_of=as_of_utc,
            period_start=period_start,
            period_end=period_end,
            observed_portfolio_return=observed_return,
            reconstructed_portfolio_return=reconstructed,
            reconciliation_error=reconciliation_error,
            market_contribution=market,
            fx_contribution=fx,
            factor_contributions=factors,
            explained_return=explained,
            residual_return=residual,
            constituents=child_tuple,
            evidence={"observedPortfolioReturn": observed_meta},
        )
