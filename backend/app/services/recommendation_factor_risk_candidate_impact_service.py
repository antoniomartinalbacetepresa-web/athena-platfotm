from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


@dataclass(frozen=True)
class RecommendationFactorRiskCandidateImpact:
    as_of: str
    candidate: dict[str, Any]
    baseline_invested_weight: float
    baseline_cash_weight: float
    post_invested_weight: float
    post_cash_weight: float
    comparable_factors: tuple[str, ...]
    coverage_lost_factors: tuple[str, ...]
    baseline_weighted_exposures: dict[str, float]
    post_weighted_exposures: dict[str, float]
    factor_exposure_deltas: dict[str, float]
    baseline_comparable_gross_exposure: float
    post_comparable_gross_exposure: float
    comparable_gross_exposure_delta: float
    baseline_comparable_max_abs_exposure: float
    post_comparable_max_abs_exposure: float
    comparable_max_abs_exposure_delta: float
    production_eligible: bool

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_ready",
            "asOf": self.as_of,
            "candidate": dict(self.candidate),
            "baselineInvestedWeight": self.baseline_invested_weight,
            "baselineCashWeight": self.baseline_cash_weight,
            "postInvestedWeight": self.post_invested_weight,
            "postCashWeight": self.post_cash_weight,
            "comparableFactors": list(self.comparable_factors),
            "coverageLostFactors": list(self.coverage_lost_factors),
            "baselineWeightedExposures": dict(self.baseline_weighted_exposures),
            "postWeightedExposures": dict(self.post_weighted_exposures),
            "factorExposureDeltas": dict(self.factor_exposure_deltas),
            "baselineComparableGrossExposure": self.baseline_comparable_gross_exposure,
            "postComparableGrossExposure": self.post_comparable_gross_exposure,
            "comparableGrossExposureDelta": self.comparable_gross_exposure_delta,
            "baselineComparableMaxAbsExposure": self.baseline_comparable_max_abs_exposure,
            "postComparableMaxAbsExposure": self.post_comparable_max_abs_exposure,
            "comparableMaxAbsExposureDelta": self.comparable_max_abs_exposure_delta,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "isWeightingReady": False,
            "policy": {
                "funding": "candidate_weight_is_explicit_caller_input_and_must_be_funded_from_existing_cash",
                "comparison": "only_factors_fully_covered_before_and_after_are_compared",
                "missingFactorCoverage": "coverage_loss_is_reported_never_imputed_as_zero",
                "covariance": "not_estimated_no_marginal_variance_or_risk_contribution_claim",
                "fx": "usd_fx_remains_explicit_and_is_never_silently_hedged",
                "thresholds": "not_calibrated",
                "interpretation": "candidate_factor_exposure_impact_not_position_sizing_or_trade_advice",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationFactorRiskCandidateImpactService:
    """Measure the PIT factor-exposure impact of an explicit cash-funded candidate.

    This is deliberately not a covariance model and therefore does not claim
    marginal variance, expected diversification benefit, optimal sizing, or a
    buy/sell/hold decision. Comparisons are restricted to factors with complete
    coverage both before and after adding the candidate.
    """

    def __init__(self, *, factor_risk_service: RecommendationFactorRiskService | None = None) -> None:
        self._factor_risk_service = factor_risk_service or RecommendationFactorRiskService()

    def evaluate(
        self,
        *,
        as_of: datetime,
        positions: tuple[FactorRiskPositionInput, ...],
        candidate: FactorRiskPositionInput,
    ) -> RecommendationFactorRiskCandidateImpact:
        baseline = self._factor_risk_service.evaluate(as_of=as_of, positions=positions)

        candidate_weight = self._finite(candidate.weight, "candidate.weight")
        if candidate_weight <= 0.0:
            raise ValueError("candidate.weight debe ser mayor que cero.")
        if candidate_weight > baseline.cash_weight + 1e-12:
            raise ValueError(
                "candidate.weight no puede superar el efectivo disponible; este diagnóstico no asume ventas ni rebalanceos ocultos."
            )

        post = self._factor_risk_service.evaluate(
            as_of=as_of,
            positions=positions + (candidate,),
        )

        baseline_fully = set(baseline.fully_covered_factors)
        post_fully = set(post.fully_covered_factors)
        comparable = tuple(sorted(baseline_fully & post_fully))
        if not comparable:
            raise ValueError(
                "No existen factores con cobertura completa comparables antes y después de añadir el candidato."
            )
        coverage_lost = tuple(sorted(baseline_fully - post_fully))

        baseline_exposures = {
            factor: self._finite(baseline.weighted_exposures[factor], f"baseline:{factor}")
            for factor in comparable
        }
        post_exposures = {
            factor: self._finite(post.weighted_exposures[factor], f"post:{factor}")
            for factor in comparable
        }
        deltas = {
            factor: self._finite(
                post_exposures[factor] - baseline_exposures[factor],
                f"delta:{factor}",
            )
            for factor in comparable
        }

        baseline_gross = self._finite(
            sum(abs(value) for value in baseline_exposures.values()),
            "baseline_comparable_gross_exposure",
        )
        post_gross = self._finite(
            sum(abs(value) for value in post_exposures.values()),
            "post_comparable_gross_exposure",
        )
        baseline_max = self._finite(
            max((abs(value) for value in baseline_exposures.values()), default=0.0),
            "baseline_comparable_max_abs_exposure",
        )
        post_max = self._finite(
            max((abs(value) for value in post_exposures.values()), default=0.0),
            "post_comparable_max_abs_exposure",
        )

        candidate_payload = next(
            position
            for position in post.positions
            if int(position["instrumentId"]) == int(candidate.instrument_id)
        )

        return RecommendationFactorRiskCandidateImpact(
            as_of=post.as_of,
            candidate=dict(candidate_payload),
            baseline_invested_weight=baseline.invested_weight,
            baseline_cash_weight=baseline.cash_weight,
            post_invested_weight=post.invested_weight,
            post_cash_weight=post.cash_weight,
            comparable_factors=comparable,
            coverage_lost_factors=coverage_lost,
            baseline_weighted_exposures=baseline_exposures,
            post_weighted_exposures=post_exposures,
            factor_exposure_deltas=deltas,
            baseline_comparable_gross_exposure=baseline_gross,
            post_comparable_gross_exposure=post_gross,
            comparable_gross_exposure_delta=self._finite(
                post_gross - baseline_gross,
                "comparable_gross_exposure_delta",
            ),
            baseline_comparable_max_abs_exposure=baseline_max,
            post_comparable_max_abs_exposure=post_max,
            comparable_max_abs_exposure_delta=self._finite(
                post_max - baseline_max,
                "comparable_max_abs_exposure_delta",
            ),
            production_eligible=False,
        )

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
