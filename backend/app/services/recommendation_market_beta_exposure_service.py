from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.repositories.market_observation_repository import MarketObservationRepository


class RecommendationMarketBetaExposureService:
    """Derive a reproducible PIT market beta from immutable market observations."""

    MIN_RETURN_SAMPLES = 20
    MAX_PRICE_POINTS = 1000

    def __init__(self, repository: MarketObservationRepository | None = None) -> None:
        self._repository = repository or MarketObservationRepository()

    def evaluate(
        self,
        *,
        instrument_id: int,
        benchmark_instrument_id: int,
        source_provider: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        if instrument_id <= 0 or benchmark_instrument_id <= 0:
            raise ValueError("instrument_id y benchmark_instrument_id deben ser positivos.")
        if instrument_id == benchmark_instrument_id:
            raise ValueError("instrumento y benchmark deben ser distintos.")
        provider = self._text(source_provider, "source_provider")
        start = self._utc(period_start, "period_start")
        end = self._utc(period_end, "period_end")
        cutoff = self._utc(as_of, "as_of")
        if end <= start:
            raise ValueError("period_end debe ser posterior a period_start.")
        if end > cutoff:
            raise ValueError("period_end no puede ser posterior a as_of.")

        asset_rows = self._repository.list_for_instrument(
            instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=start,
            observed_to=end,
        )
        benchmark_rows = self._repository.list_for_instrument(
            benchmark_instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=start,
            observed_to=end,
        )
        asset = self._prices(asset_rows, "instrument")
        benchmark = self._prices(benchmark_rows, "benchmark")
        common = sorted(set(asset) & set(benchmark))
        if len(common) > self.MAX_PRICE_POINTS:
            common = common[-self.MAX_PRICE_POINTS :]
        if len(common) < self.MIN_RETURN_SAMPLES + 1:
            raise ValueError(
                f"Se requieren al menos {self.MIN_RETURN_SAMPLES + 1} precios PIT emparejados."
            )

        asset_returns: list[float] = []
        market_returns: list[float] = []
        used: list[dict[str, Any]] = []
        for previous_at, current_at in zip(common, common[1:]):
            previous_asset = asset[previous_at]
            current_asset = asset[current_at]
            previous_market = benchmark[previous_at]
            current_market = benchmark[current_at]
            asset_return = current_asset["price"] / previous_asset["price"] - 1.0
            market_return = current_market["price"] / previous_market["price"] - 1.0
            self._finite(asset_return, "asset_return")
            self._finite(market_return, "market_return")
            asset_returns.append(asset_return)
            market_returns.append(market_return)
            used.append(
                {
                    "observedAt": current_at,
                    "instrumentPrice": current_asset["price"],
                    "benchmarkPrice": current_market["price"],
                    "instrumentRetrievedAt": current_asset["retrievedAt"],
                    "benchmarkRetrievedAt": current_market["retrievedAt"],
                }
            )

        n = len(asset_returns)
        mean_asset = sum(asset_returns) / n
        mean_market = sum(market_returns) / n
        variance_market = sum((value - mean_market) ** 2 for value in market_returns) / (n - 1)
        if not math.isfinite(variance_market) or variance_market <= 1e-18:
            raise ValueError("La varianza del benchmark es insuficiente para estimar beta.")
        covariance = sum(
            (asset_return - mean_asset) * (market_return - mean_market)
            for asset_return, market_return in zip(asset_returns, market_returns)
        ) / (n - 1)
        beta = self._finite(covariance / variance_market, "market_beta")
        if beta < -10.0 or beta > 10.0:
            raise ValueError("Beta de mercado fuera del rango de seguridad [-10, 10].")

        available_at = max(
            datetime.fromisoformat(str(item[key]))
            for item in used
            for key in ("instrumentRetrievedAt", "benchmarkRetrievedAt")
        ).astimezone(timezone.utc)
        if available_at > cutoff:
            raise RuntimeError("La evidencia beta contiene conocimiento posterior a as_of.")

        artifact: dict[str, Any] = {
            "module": "pit_market_beta_exposure",
            "instrumentId": instrument_id,
            "benchmarkInstrumentId": benchmark_instrument_id,
            "sourceProvider": provider,
            "periodStart": start.isoformat(),
            "periodEnd": end.isoformat(),
            "asOf": cutoff.isoformat(),
            "availableAt": available_at.isoformat(),
            "sampleCount": n,
            "factors": {"market": beta},
            "observations": used,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_and_retrieved_at_lte_as_of",
                "missingFactors": "not_inferred",
                "estimator": "sample_covariance_asset_market_over_sample_variance_market",
            },
        }
        artifact["factorExposureKey"] = self._key(artifact)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "pit_market_beta_exposure":
            raise ValueError("Artifact de beta tiene módulo inválido.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Artifact beta violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Artifact beta intentó habilitar producción/weighting.")
        factors = artifact.get("factors")
        if not isinstance(factors, dict) or set(factors) != {"market"}:
            raise ValueError("Artifact beta debe contener exclusivamente factor market.")
        self._finite(factors["market"], "factors.market")
        count = artifact.get("sampleCount")
        observations = artifact.get("observations")
        if isinstance(count, bool) or not isinstance(count, int) or count < self.MIN_RETURN_SAMPLES:
            raise ValueError("Artifact beta carece de muestra suficiente.")
        if not isinstance(observations, list) or len(observations) != count:
            raise ValueError("Artifact beta perdió observations canónicas.")
        as_of = self._parse_utc(artifact.get("asOf"), "asOf")
        available = self._parse_utc(artifact.get("availableAt"), "availableAt")
        if available > as_of:
            raise ValueError("Artifact beta viola PIT/no-lookahead.")
        expected = self._key(artifact)
        key = str(artifact.get("factorExposureKey") or "")
        if key != expected:
            raise ValueError("factorExposureKey no coincide con el artifact canónico.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise ValueError("Artifact beta intentó habilitar trading.")
        return artifact

    def _prices(self, rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            observed = str(row.get("observed_at") or "")
            if not observed or observed in result:
                raise ValueError(f"{label} contiene observaciones temporales duplicadas.")
            raw_price = row.get("adjusted_close") if row.get("adjusted_close") is not None else row.get("close")
            price = self._finite(raw_price, f"{label}.price")
            if price <= 0.0:
                raise ValueError(f"{label}.price debe ser positivo.")
            retrieved = self._parse_utc(row.get("retrieved_at"), f"{label}.retrieved_at")
            observed_dt = self._parse_utc(observed, f"{label}.observed_at")
            if observed_dt > retrieved:
                raise ValueError(f"{label} viola observed_at <= retrieved_at.")
            result[observed_dt.isoformat()] = {
                "price": price,
                "retrievedAt": retrieved.isoformat(),
            }
        return result

    def _key(self, artifact: dict[str, Any]) -> str:
        canonical = {key: value for key, value in artifact.items() if key != "factorExposureKey"}
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
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
