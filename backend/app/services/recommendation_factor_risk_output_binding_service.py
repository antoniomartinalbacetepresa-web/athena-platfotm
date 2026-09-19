from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Mapping, Sequence

from app.services.recommendation_factor_risk_service import FactorRiskPositionInput


class RecommendationFactorRiskOutputBindingService:
    """Fail closed unless Factor Risk output exactly reflects derived PIT inputs.

    The API derives portfolio weights and sealed factors before invoking the
    diagnostic engine. Structural output validation alone is insufficient: a
    faulty or replaced engine could otherwise return a different sealed factor,
    omit evidence, change a canonical weight, or publish aggregates that no
    longer reconcile to the evidence supplied to it. This service independently
    binds the returned position-level and aggregate diagnostics back to the
    exact derived inputs.
    """

    _ABS_TOLERANCE = 1e-12

    @classmethod
    def validate(
        cls,
        *,
        payload: Mapping[str, object],
        expected_positions: Sequence[FactorRiskPositionInput],
    ) -> None:
        if not expected_positions:
            raise ValueError("Factor Risk output binding requiere posiciones derivadas.")

        raw_positions = payload.get("positions")
        if not isinstance(raw_positions, list):
            raise ValueError("Factor Risk output binding perdió positions.")
        if len(raw_positions) != len(expected_positions):
            raise ValueError("Factor Risk output binding cambió el número de posiciones.")

        expected_by_id: dict[int, FactorRiskPositionInput] = {}
        for item in expected_positions:
            if item.instrument_id in expected_by_id:
                raise ValueError("Factor Risk output binding recibió instrumentId derivado duplicado.")
            expected_by_id[item.instrument_id] = item

        actual_by_id: dict[int, Mapping[str, object]] = {}
        for raw in raw_positions:
            if not isinstance(raw, Mapping):
                raise ValueError("Factor Risk output binding recibió posición de salida inválida.")
            instrument_id = raw.get("instrumentId")
            if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):
                raise ValueError("Factor Risk output binding perdió instrumentId de salida.")
            if instrument_id in actual_by_id:
                raise ValueError("Factor Risk output binding detectó instrumentId de salida duplicado.")
            actual_by_id[instrument_id] = raw

        if set(actual_by_id) != set(expected_by_id):
            raise ValueError("Factor Risk output binding cambió la identidad de posiciones.")

        expected_exposure: dict[str, float] = {}
        expected_coverage: dict[str, float] = {}
        for instrument_id, expected in expected_by_id.items():
            actual = actual_by_id[instrument_id]
            if str(actual.get("symbol") or "").strip().upper() != expected.symbol.strip().upper():
                raise ValueError("Factor Risk output binding cambió el símbolo derivado.")
            cls._same_number(actual.get("weight"), expected.weight, "weight")

            actual_available = cls._parse_datetime(
                actual.get("exposureAvailableAt"),
                "exposureAvailableAt",
            )
            expected_available = cls._aware_utc(
                expected.exposure_available_at,
                "expected.exposure_available_at",
            )
            if actual_available != expected_available:
                raise ValueError("Factor Risk output binding cambió exposureAvailableAt.")
            if str(actual.get("source") or "") != expected.source:
                raise ValueError("Factor Risk output binding cambió source derivado.")
            if str(actual.get("sourceRef") or "") != expected.source_ref:
                raise ValueError("Factor Risk output binding cambió sourceRef derivado.")

            actual_factors = actual.get("factors")
            if not isinstance(actual_factors, Mapping):
                raise ValueError("Factor Risk output binding perdió factors por posición.")
            if set(actual_factors) != set(expected.factors):
                raise ValueError("Factor Risk output binding añadió u omitió factores frente a evidencia derivada.")
            for factor, expected_value in expected.factors.items():
                cls._same_number(
                    actual_factors.get(factor),
                    expected_value,
                    f"factors.{factor}",
                )
                expected_exposure[factor] = expected_exposure.get(factor, 0.0) + (
                    float(expected.weight) * float(expected_value)
                )
                expected_coverage[factor] = expected_coverage.get(factor, 0.0) + float(expected.weight)

        raw_exposures = payload.get("weightedExposures")
        raw_coverage = payload.get("factorCoverageWeights")
        if not isinstance(raw_exposures, Mapping) or not isinstance(raw_coverage, Mapping):
            raise ValueError("Factor Risk output binding perdió agregados factoriales.")
        if set(raw_exposures) != set(raw_coverage):
            raise ValueError("Factor Risk output binding devolvió agregados con identidades distintas.")

        for factor in set(raw_exposures) | set(expected_exposure):
            expected_value = expected_exposure.get(factor, 0.0)
            expected_weight = expected_coverage.get(factor, 0.0)
            if factor not in raw_exposures or factor not in raw_coverage:
                raise ValueError("Factor Risk output binding omitió un agregado derivado.")
            cls._same_number(
                raw_exposures.get(factor),
                expected_value,
                f"weightedExposures.{factor}",
            )
            cls._same_number(
                raw_coverage.get(factor),
                expected_weight,
                f"factorCoverageWeights.{factor}",
            )

    @classmethod
    def _same_number(cls, raw: object, expected: float, field: str) -> None:
        actual = cls._finite(raw, field)
        expected_finite = cls._finite(expected, f"expected.{field}")
        if not math.isclose(
            actual,
            expected_finite,
            rel_tol=0.0,
            abs_tol=cls._ABS_TOLERANCE,
        ):
            raise ValueError(f"Factor Risk output binding no reconcilió {field} con evidencia derivada.")

    @staticmethod
    def _finite(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"Factor Risk output binding encontró {field} no finito.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Factor Risk output binding encontró {field} no numérico.") from exc
        if not math.isfinite(value):
            raise ValueError(f"Factor Risk output binding encontró {field} no finito.")
        return value

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Factor Risk output binding requiere timezone en {field}.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return cls._aware_utc(raw, field)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"Factor Risk output binding perdió {field}.")
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Factor Risk output binding recibió {field} inválido.") from exc
        return cls._aware_utc(value, field)
