from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.repositories.market_observation_repository import MarketObservationRepository


class RecommendationPriceFactorExposureService:
    """Derive momentum and low-volatility diagnostics from immutable PIT prices."""

    MIN_RETURN_SAMPLES = 20
    MAX_PRICE_POINTS = 1000

    def __init__(self, repository: MarketObservationRepository | None = None) -> None:
        self._repository = repository or MarketObservationRepository()

    def evaluate(
        self,
        *,
        instrument_id: int,
        source_provider: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        provider = self._text(source_provider, "source_provider")
        start = self._utc(period_start, "period_start")
        end = self._utc(period_end, "period_end")
        cutoff = self._utc(as_of, "as_of")
        if end <= start:
            raise ValueError("period_end debe ser posterior a period_start.")
        if end > cutoff:
            raise ValueError("period_end no puede ser posterior a as_of.")

        rows = self._repository.list_for_instrument(
            instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=start,
            observed_to=end,
        )
        prices = self._prices(rows)
        ordered = sorted(prices)
        if len(ordered) > self.MAX_PRICE_POINTS:
            ordered = ordered[-self.MAX_PRICE_POINTS :]
        if len(ordered) < self.MIN_RETURN_SAMPLES + 1:
            raise ValueError(
                f"Se requieren al menos {self.MIN_RETURN_SAMPLES + 1} precios PIT para momentum/low-volatility."
            )

        returns: list[float] = []
        observations: list[dict[str, Any]] = []
        for previous_at, current_at in zip(ordered, ordered[1:]):
            previous = prices[previous_at]
            current = prices[current_at]
            value = self._finite(current["price"] / previous["price"] - 1.0, "return")
            returns.append(value)
            observations.append(
                {
                    "observedAt": current_at,
                    "price": current["price"],
                    "retrievedAt": current["retrievedAt"],
                }
            )

        first_price = prices[ordered[0]]["price"]
        last_price = prices[ordered[-1]]["price"]
        momentum = self._finite(last_price / first_price - 1.0, "momentum")
        n = len(returns)
        mean_return = sum(returns) / n
        variance = sum((value - mean_return) ** 2 for value in returns) / (n - 1)
        if not math.isfinite(variance) or variance < 0.0:
            raise ValueError("La varianza de retornos no es válida.")
        realized_volatility = self._finite(math.sqrt(variance), "realized_volatility")
        low_volatility = self._finite(-realized_volatility, "low_volatility")

        available_at = max(
            self._parse_utc(prices[point]["retrievedAt"], "retrievedAt")
            for point in ordered
        )
        if available_at > cutoff:
            raise RuntimeError("La evidencia de factores de precio contiene conocimiento posterior a as_of.")

        artifact: dict[str, Any] = {
            "module": "pit_price_factor_exposure",
            "instrumentId": instrument_id,
            "sourceProvider": provider,
            "periodStart": start.isoformat(),
            "periodEnd": end.isoformat(),
            "asOf": cutoff.isoformat(),
            "availableAt": available_at.isoformat(),
            "sampleCount": n,
            "factors": {
                "momentum": momentum,
                "low_volatility": low_volatility,
            },
            "diagnostics": {
                "realizedVolatilityUnannualized": realized_volatility,
                "meanObservedReturn": self._finite(mean_return, "mean_return"),
            },
            "observations": observations,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_and_retrieved_at_lte_as_of",
                "missingFactors": "not_inferred",
                "momentumEstimator": "total_return_first_to_last_pit_price",
                "lowVolatilityEstimator": "negative_sample_standard_deviation_of_observed_returns_unannualized",
                "frequencyNormalization": "not_assumed",
                "thresholds": "not_calibrated",
                "purpose": "factor_risk_diagnostic_only",
            },
        }
        artifact["factorExposureKey"] = self._key(artifact)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "pit_price_factor_exposure":
            raise ValueError("Artifact de factores de precio tiene módulo inválido.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Artifact de factores de precio violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Artifact de factores de precio intentó habilitar producción/weighting.")
        instrument_id = artifact.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("Artifact de factores de precio perdió instrumentId válido.")
        factors = artifact.get("factors")
        if not isinstance(factors, dict) or set(factors) != {"momentum", "low_volatility"}:
            raise ValueError("Artifact debe contener exclusivamente momentum y low_volatility.")
        self._finite(factors["momentum"], "factors.momentum")
        low_volatility = self._finite(factors["low_volatility"], "factors.low_volatility")
        if low_volatility > 1e-15:
            raise ValueError("low_volatility sellado no puede ser positivo con este estimador.")
        count = artifact.get("sampleCount")
        observations = artifact.get("observations")
        if isinstance(count, bool) or not isinstance(count, int) or count < self.MIN_RETURN_SAMPLES:
            raise ValueError("Artifact de factores de precio carece de muestra suficiente.")
        if not isinstance(observations, list) or len(observations) != count:
            raise ValueError("Artifact de factores de precio perdió observations canónicas.")
        as_of = self._parse_utc(artifact.get("asOf"), "asOf")
        available = self._parse_utc(artifact.get("availableAt"), "availableAt")
        if available > as_of:
            raise ValueError("Artifact de factores de precio viola PIT/no-lookahead.")
        policy = artifact.get("policy")
        if (
            not isinstance(policy, dict)
            or policy.get("automaticTrading") is not False
            or policy.get("frequencyNormalization") != "not_assumed"
            or policy.get("thresholds") != "not_calibrated"
        ):
            raise ValueError("Artifact de factores de precio perdió límites de seguridad/calibración.")
        expected = self._key(artifact)
        if str(artifact.get("factorExposureKey") or "") != expected:
            raise ValueError("factorExposureKey no coincide con el artifact canónico.")
        return artifact

    def _prices(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            observed = self._parse_utc(row.get("observed_at"), "observed_at")
            key = observed.isoformat()
            if key in result:
                raise ValueError("El instrumento contiene observaciones temporales duplicadas.")
            raw_price = row.get("adjusted_close") if row.get("adjusted_close") is not None else row.get("close")
            price = self._finite(raw_price, "price")
            if price <= 0.0:
                raise ValueError("price debe ser positivo.")
            retrieved = self._parse_utc(row.get("retrieved_at"), "retrieved_at")
            if observed > retrieved:
                raise ValueError("La observación viola observed_at <= retrieved_at.")
            result[key] = {"price": price, "retrievedAt": retrieved.isoformat()}
        return result

    def _key(self, artifact: dict[str, Any]) -> str:
        canonical = {key: value for key, value in artifact.items() if key != "factorExposureKey"}
        return hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico finito.")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"{field} debe ser numérico finito.")
        return numeric

    @staticmethod
    def _utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_utc(cls, value: object, field: str) -> datetime:
        if isinstance(value, datetime):
            return cls._utc(value, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser timestamp ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._utc(parsed, field)
