from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


_ALLOWED_FACTORS = frozenset(
    {
        "market",
        "size",
        "value",
        "momentum",
        "quality",
        "low_volatility",
        "rates",
        "usd_fx",
    }
)


@dataclass(frozen=True)
class FactorRiskPositionInput:
    instrument_id: int
    symbol: str
    weight: float
    exposure_available_at: datetime
    source: str
    source_ref: str
    factors: Mapping[str, float]


@dataclass(frozen=True)
class RecommendationFactorRisk:
    as_of: str
    position_count: int
    invested_weight: float
    cash_weight: float
    positions: tuple[dict[str, Any], ...]
    weighted_exposures: dict[str, float]
    factor_coverage_weights: dict[str, float]
    fully_covered_factors: tuple[str, ...]
    gross_factor_exposure: float
    max_absolute_factor_exposure: float
    dominant_factor: str | None
    production_eligible: bool

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_ready",
            "asOf": self.as_of,
            "positionCount": self.position_count,
            "investedWeight": self.invested_weight,
            "cashWeight": self.cash_weight,
            "positions": [dict(position) for position in self.positions],
            "weightedExposures": dict(self.weighted_exposures),
            "factorCoverageWeights": dict(self.factor_coverage_weights),
            "fullyCoveredFactors": list(self.fully_covered_factors),
            "grossFactorExposure": self.gross_factor_exposure,
            "maxAbsoluteFactorExposure": self.max_absolute_factor_exposure,
            "dominantFactor": self.dominant_factor,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "isWeightingReady": False,
            "policy": {
                "temporal": "all_factor_exposures_available_at_must_be_lte_as_of",
                "identity": "duplicate_instrument_or_symbol_forbidden",
                "finiteData": "all_weights_and_exposures_must_be_finite",
                "provenance": "every_position_requires_source_and_source_ref_and_is_returned_for_audit",
                "missingFactorCoverage": "reported_explicitly_never_imputed_as_zero",
                "fx": "usd_fx_is_explicit_factor_not_silently_netting_currency_risk",
                "dominantFactor": "only_selected_from_factors_covering_all_invested_weight",
                "thresholds": "not_calibrated",
                "interpretation": "portfolio_factor_diagnostic_not_position_sizing_or_trade_advice",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationFactorRiskService:
    """Build a provenance-bound PIT portfolio factor diagnostic.

    Factor exposures are explicit caller-supplied research evidence. This service
    does not infer missing exposures, fill unavailable factors, estimate covariance,
    size positions or issue buy/sell/hold decisions. Missing factor coverage is
    reported explicitly instead of being silently treated as a zero exposure.
    """

    def evaluate(
        self,
        *,
        as_of: datetime,
        positions: tuple[FactorRiskPositionInput, ...],
    ) -> RecommendationFactorRisk:
        cutoff = self._aware_utc(as_of, "as_of")
        if not positions:
            raise ValueError("positions debe contener al menos una posición.")
        if len(positions) > 500:
            raise ValueError("positions no puede superar 500 posiciones.")

        seen_ids: set[int] = set()
        seen_symbols: set[str] = set()
        weighted = {factor: 0.0 for factor in sorted(_ALLOWED_FACTORS)}
        coverage = {factor: 0.0 for factor in sorted(_ALLOWED_FACTORS)}
        invested_weight = 0.0
        position_evidence: list[dict[str, Any]] = []

        for position in positions:
            instrument_id = self._positive_int(position.instrument_id, "instrument_id")
            symbol = str(position.symbol or "").strip().upper()
            if not symbol:
                raise ValueError("symbol es obligatorio.")
            if instrument_id in seen_ids or symbol in seen_symbols:
                raise ValueError("No se permiten instrumentos o símbolos duplicados.")
            seen_ids.add(instrument_id)
            seen_symbols.add(symbol)

            weight = self._finite(position.weight, "weight")
            if weight < 0.0 or weight > 1.0:
                raise ValueError("weight debe estar en [0, 1].")
            invested_weight = self._finite(invested_weight + weight, "invested_weight")
            if invested_weight > 1.0 + 1e-12:
                raise ValueError("La suma de weights no puede superar 1.")

            available_at = self._aware_utc(position.exposure_available_at, "exposure_available_at")
            if available_at > cutoff:
                raise ValueError(
                    "exposure_available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio."
                )
            source = self._required_text(position.source, "source")
            source_ref = self._required_text(position.source_ref, "source_ref")

            if not isinstance(position.factors, Mapping) or not position.factors:
                raise ValueError("factors debe contener al menos una exposición explícita.")
            normalized_factors: dict[str, float] = {}
            for raw_name, raw_value in position.factors.items():
                name = str(raw_name or "").strip().lower()
                if name not in _ALLOWED_FACTORS:
                    allowed = ", ".join(sorted(_ALLOWED_FACTORS))
                    raise ValueError(f"Factor no soportado: {name or '<vacío>'}. Permitidos: {allowed}.")
                if name in normalized_factors:
                    raise ValueError("No se permiten factores duplicados por posición.")
                exposure = self._finite(raw_value, f"factor:{name}")
                if exposure < -10.0 or exposure > 10.0:
                    raise ValueError("Las exposiciones factoriales deben estar en [-10, 10].")
                normalized_factors[name] = exposure

            for factor, exposure in normalized_factors.items():
                weighted[factor] = self._finite(
                    weighted[factor] + weight * exposure,
                    f"weighted:{factor}",
                )
                coverage[factor] = self._finite(
                    coverage[factor] + weight,
                    f"coverage:{factor}",
                )

            position_evidence.append(
                {
                    "instrumentId": instrument_id,
                    "symbol": symbol,
                    "weight": weight,
                    "exposureAvailableAt": available_at.isoformat(),
                    "source": source,
                    "sourceRef": source_ref,
                    "factors": dict(sorted(normalized_factors.items())),
                }
            )

        invested_weight = min(max(invested_weight, 0.0), 1.0)
        cash_weight = self._finite(1.0 - invested_weight, "cash_weight")
        fully_covered = tuple(
            factor
            for factor in sorted(_ALLOWED_FACTORS)
            if invested_weight > 0.0 and abs(coverage[factor] - invested_weight) <= 1e-12
        )
        fully_covered_values = {factor: weighted[factor] for factor in fully_covered}
        gross = self._finite(
            sum(abs(value) for value in fully_covered_values.values()),
            "gross_factor_exposure",
        )
        maximum = self._finite(
            max((abs(value) for value in fully_covered_values.values()), default=0.0),
            "max_absolute_factor_exposure",
        )
        dominant = None
        non_zero_fully_covered = {
            factor: value
            for factor, value in fully_covered_values.items()
            if abs(value) > 1e-15
        }
        if non_zero_fully_covered:
            dominant = max(
                non_zero_fully_covered,
                key=lambda factor: (abs(non_zero_fully_covered[factor]), factor),
            )

        return RecommendationFactorRisk(
            as_of=cutoff.isoformat(),
            position_count=len(positions),
            invested_weight=invested_weight,
            cash_weight=cash_weight,
            positions=tuple(position_evidence),
            weighted_exposures=weighted,
            factor_coverage_weights=coverage,
            fully_covered_factors=fully_covered,
            gross_factor_exposure=gross,
            max_absolute_factor_exposure=maximum,
            dominant_factor=dominant,
            production_eligible=False,
        )

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar provenance.")
        return text

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser un entero positivo.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser un entero positivo.") from exc
        if parsed <= 0 or isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{field} debe ser un entero positivo.")
        return parsed

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
