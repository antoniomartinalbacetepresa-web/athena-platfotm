from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from app.repositories.recommendation_quality_factor_exposure_repository import (
    RecommendationQualityFactorExposureRepository,
)


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
    quality_exposure_key: str | None = None


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
                "quality": "quality_requires_persisted_tamper_verified_pit_factor_exposure_key",
                "dominantFactor": "only_selected_from_factors_covering_all_invested_weight",
                "thresholds": "not_calibrated",
                "interpretation": "portfolio_factor_diagnostic_not_position_sizing_or_trade_advice",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationFactorRiskService:
    """Build a provenance-bound PIT portfolio factor diagnostic.

    Caller-supplied research evidence is allowed only for factors that have not
    yet been sealed upstream. Quality is a sealed factor: whenever present it
    must reconcile exactly to a persisted, tamper-verified PIT quality artifact.
    The service never infers missing exposures, estimates covariance, sizes
    positions or issues buy/sell/hold decisions.
    """

    def __init__(
        self,
        *,
        quality_repository: RecommendationQualityFactorExposureRepository | None = None,
    ) -> None:
        self._quality_repository = quality_repository or RecommendationQualityFactorExposureRepository()

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

            quality_key = position.quality_exposure_key
            if "quality" in normalized_factors:
                self._validate_sealed_quality(
                    instrument_id=instrument_id,
                    cutoff=cutoff,
                    exposure_available_at=available_at,
                    source=source,
                    source_ref=source_ref,
                    quality_value=normalized_factors["quality"],
                    quality_exposure_key=quality_key,
                )
            elif quality_key is not None:
                raise ValueError("quality_exposure_key no puede existir sin factor quality.")

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

    def _validate_sealed_quality(
        self,
        *,
        instrument_id: int,
        cutoff: datetime,
        exposure_available_at: datetime,
        source: str,
        source_ref: str,
        quality_value: float,
        quality_exposure_key: str | None,
    ) -> None:
        explicit_key = str(quality_exposure_key or "").strip().lower()
        referenced_keys = [
            part.strip().split(":", 1)[1].strip().lower()
            for part in source_ref.split(";")
            if part.strip().lower().startswith("quality:") and ":" in part.strip()
        ]
        if explicit_key:
            if not self._sha256(explicit_key):
                raise ValueError("quality requiere quality_exposure_key SHA-256 sellada.")
            if referenced_keys != [explicit_key]:
                raise ValueError("Factor quality perdió sourceRef único de quality_exposure_key.")
            key = explicit_key
        else:
            if len(referenced_keys) != 1 or not self._sha256(referenced_keys[0]):
                raise ValueError("quality requiere quality_exposure_key SHA-256 sellada en sourceRef.")
            key = referenced_keys[0]

        try:
            record = self._quality_repository.get(factor_exposure_key=key)
        except ValueError as exc:
            raise ValueError(f"quality_exposure_key inválida: {exc}") from exc
        if record is None:
            raise ValueError("No existe quality factor exposure persistido con esa identidad.")
        artifact = record.get("artifact")
        if not isinstance(artifact, Mapping):
            raise ValueError("Quality factor exposure persistido perdió artifact.")
        artifact_key = str(artifact.get("factorExposureKey") or "").strip().lower()
        if artifact_key != key or not self._sha256(artifact_key):
            raise ValueError("Quality factor exposure perdió identidad sellada.")
        if artifact.get("instrumentId") != instrument_id:
            raise ValueError("quality_exposure_key pertenece a otro instrumento.")
        artifact_as_of = self._parse_datetime(artifact.get("asOf"), "quality.asOf")
        artifact_available = self._parse_datetime(artifact.get("availableAt"), "quality.availableAt")
        if artifact_as_of != cutoff:
            raise ValueError("quality_exposure_key pertenece a otro as_of.")
        if artifact_available > cutoff or artifact_available > exposure_available_at:
            raise ValueError("Quality factor exposure viola PIT/exposure_available_at.")
        factors = artifact.get("factors")
        if not isinstance(factors, Mapping) or set(factors) != {"quality"}:
            raise ValueError("Quality factor exposure persistido contiene factores inesperados.")
        sealed_value = self._finite(factors.get("quality"), "sealed_quality")
        if sealed_value < -1.0 - 1e-12 or sealed_value > 1.0 + 1e-12:
            raise ValueError("Quality factor exposure sellado salió de [-1,1].")
        if not math.isclose(quality_value, sealed_value, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("Factor quality no reconcilia con quality_exposure_key sellada.")
        if "sealed_quality_factor" not in {part.strip() for part in source.split("+")}:
            raise ValueError("Factor quality perdió provenance sealed_quality_factor.")
        if f"quality:{key}" not in {part.strip() for part in source_ref.split(";")}:
            raise ValueError("Factor quality perdió sourceRef de quality_exposure_key.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Quality factor exposure violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Quality factor exposure intentó habilitar producción/weighting.")

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

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_datetime(self, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return self._aware_utc(raw, field)
        text = str(raw or "").strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return self._aware_utc(parsed, field)
