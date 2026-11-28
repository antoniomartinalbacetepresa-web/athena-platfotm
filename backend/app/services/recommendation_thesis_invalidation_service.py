from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_ALLOWED_OPERATORS = frozenset({"lt", "lte", "gt", "gte"})
_FORBIDDEN_PRICE_METRICS = frozenset(
    {
        "price",
        "share_price",
        "stock_price",
        "drawdown",
        "price_drawdown",
        "return",
        "total_return",
    }
)


@dataclass(frozen=True)
class RecommendationThesisCriterionInput:
    name: str
    metric: str
    operator: str
    threshold: float
    observed_value: float
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class RecommendationThesisCriterionResult:
    name: str
    metric: str
    operator: str
    threshold: float
    observed_value: float
    breached: bool
    available_at: str
    source: str
    source_ref: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "observedValue": self.observed_value,
            "breached": self.breached,
            "availableAt": self.available_at,
            "source": self.source,
            "sourceRef": self.source_ref,
        }


@dataclass(frozen=True)
class RecommendationThesisInvalidation:
    status: str
    symbol: str
    as_of: str
    criteria: tuple[RecommendationThesisCriterionResult, ...]
    breached_count: int
    thesis_invalidation_evidence_present: bool
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "asOf": self.as_of,
            "criteria": [criterion.to_api_dict() for criterion in self.criteria],
            "breachedCount": self.breached_count,
            "thesisInvalidationEvidencePresent": self.thesis_invalidation_evidence_present,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "isWeightingReady": False,
            "reason": self.reason,
            "policy": {
                "temporal": "every_observation_available_at_must_be_lte_as_of",
                "provenance": "every_criterion_requires_explicit_source_and_source_ref",
                "criteria": "caller_supplied_precommitted_thresholds_no_hidden_rules",
                "priceOnlyInvalidation": "forbidden",
                "interpretation": "breach_evidence_requires_reassessment_not_automatic_sell",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationThesisInvalidationService:
    """Evaluate explicit PIT thesis-break criteria without issuing sell advice.

    Criteria are caller-supplied, provenance-bound and evaluated only with
    observations that were available at the requested PIT cutoff. Price-only
    criteria are deliberately forbidden: a falling share price is not, by itself,
    evidence that the underlying investment thesis has become false.

    A breach means that a precommitted thesis assumption deserves reassessment.
    It does not assign SELL/HOLD, score, conviction, portfolio weight or execution.
    """

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        criteria: tuple[RecommendationThesisCriterionInput, ...],
    ) -> RecommendationThesisInvalidation:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        cutoff = self._aware_utc(as_of, "as_of")
        if not isinstance(criteria, tuple) or not criteria:
            raise ValueError("criteria debe contener al menos un criterio de invalidación explícito.")
        if len(criteria) > 50:
            raise ValueError("criteria no puede contener más de 50 criterios.")

        seen_names: set[str] = set()
        results: list[RecommendationThesisCriterionResult] = []
        for raw in criteria:
            criterion = self._validate_criterion(raw, as_of=cutoff)
            if criterion.name in seen_names:
                raise ValueError("Los nombres de criterios de invalidación no pueden repetirse.")
            seen_names.add(criterion.name)
            breached = self._breached(
                observed=criterion.observed_value,
                operator=criterion.operator,
                threshold=criterion.threshold,
            )
            results.append(
                RecommendationThesisCriterionResult(
                    name=criterion.name,
                    metric=criterion.metric,
                    operator=criterion.operator,
                    threshold=criterion.threshold,
                    observed_value=criterion.observed_value,
                    breached=breached,
                    available_at=criterion.available_at.isoformat(),
                    source=criterion.source,
                    source_ref=criterion.source_ref,
                )
            )

        breached_count = sum(1 for item in results if item.breached)
        evidence_present = breached_count > 0
        reason = (
            "Existe evidencia PIT que incumple uno o más criterios predefinidos de la tesis; "
            "requiere reevaluación humana y del sistema, pero no constituye una orden de venta."
            if evidence_present
            else "No se incumple ningún criterio PIT predefinido de la tesis en este corte; esto no garantiza que la tesis sea correcta."
        )
        return RecommendationThesisInvalidation(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            as_of=cutoff.isoformat(),
            criteria=tuple(results),
            breached_count=breached_count,
            thesis_invalidation_evidence_present=evidence_present,
            production_eligible=False,
            reason=reason,
        )

    def _validate_criterion(
        self,
        value: RecommendationThesisCriterionInput,
        *,
        as_of: datetime,
    ) -> RecommendationThesisCriterionInput:
        if not isinstance(value, RecommendationThesisCriterionInput):
            raise ValueError("Cada criterio debe ser RecommendationThesisCriterionInput.")
        name = self._required_text(value.name, "criterion.name").lower()
        metric = self._required_text(value.metric, "criterion.metric").lower()
        if metric in _FORBIDDEN_PRICE_METRICS or metric.startswith("price_"):
            raise ValueError("Los criterios basados únicamente en precio/rentabilidad están prohibidos para invalidar una tesis.")
        operator = self._required_text(value.operator, "criterion.operator").lower()
        if operator not in _ALLOWED_OPERATORS:
            raise ValueError("criterion.operator debe ser uno de: lt, lte, gt, gte.")
        threshold = self._finite(value.threshold, "criterion.threshold")
        observed = self._finite(value.observed_value, "criterion.observed_value")
        available_at = self._aware_utc(value.available_at, "criterion.available_at")
        if available_at > as_of:
            raise ValueError("criterion.available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio.")
        source = self._required_text(value.source, "criterion.source")
        source_ref = self._required_text(value.source_ref, "criterion.source_ref")
        return RecommendationThesisCriterionInput(
            name=name,
            metric=metric,
            operator=operator,
            threshold=threshold,
            observed_value=observed,
            available_at=available_at,
            source=source,
            source_ref=source_ref,
        )

    def _breached(self, *, observed: float, operator: str, threshold: float) -> bool:
        if operator == "lt":
            return observed < threshold
        if operator == "lte":
            return observed <= threshold
        if operator == "gt":
            return observed > threshold
        if operator == "gte":
            return observed >= threshold
        raise RuntimeError("Operador de invalidación no soportado.")

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar semántica y provenance.")
        return text

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser numérico finito.")
        return result

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
