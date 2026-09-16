from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.repositories.market_observation_repository import MarketObservationRepository
from app.repositories.recommendation_macro_pit_observation_repository import (
    RecommendationMacroPitObservationRepository,
)


class RecommendationRateFactorExposureService:
    """Derive bounded rate sensitivity from sealed market + macro PIT evidence."""

    MIN_PAIRED_CHANGES = 20

    def __init__(
        self,
        market_repository: MarketObservationRepository | None = None,
        macro_repository: RecommendationMacroPitObservationRepository | None = None,
    ) -> None:
        self._market_repository = market_repository or MarketObservationRepository()
        self._macro_repository = macro_repository or RecommendationMacroPitObservationRepository()

    def evaluate(
        self,
        *,
        instrument_id: int,
        market_source_provider: str,
        rate_series_id: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser entero positivo.")
        provider = self._text(market_source_provider, "market_source_provider")
        if self._is_fmp(provider):
            raise ValueError("FMP no está permitido como market_source_provider.")
        series_id = self._text(rate_series_id, "rate_series_id").upper()
        start = self._utc(period_start, "period_start")
        end = self._utc(period_end, "period_end")
        cutoff = self._utc(as_of, "as_of")
        if end <= start:
            raise ValueError("period_end debe ser posterior a period_start.")
        if end > cutoff:
            raise ValueError("period_end no puede ser posterior a as_of.")

        market_rows = self._market_repository.list_for_instrument(
            instrument_id,
            source_provider=provider,
            knowledge_cutoff=cutoff,
            observed_from=start,
            observed_to=end,
        )
        price_by_day: dict[str, tuple[float, str, str]] = {}
        for row in market_rows:
            observed = self._parse(row.get("observed_at"), "market.observed_at")
            retrieved = self._parse(row.get("retrieved_at"), "market.retrieved_at")
            if observed > retrieved or retrieved > cutoff:
                raise RuntimeError("Market evidence de rates viola PIT/no-lookahead.")
            raw_price = row.get("adjusted_close") if row.get("adjusted_close") is not None else row.get("close")
            if raw_price is None:
                continue
            price = self._positive(raw_price, "market.price")
            day = observed.date().isoformat()
            if day in price_by_day:
                raise ValueError("Market evidence contiene más de un precio por fecha para rates.")
            price_by_day[day] = (price, observed.isoformat(), retrieved.isoformat())

        macro_records = self._macro_repository.get_series_at_or_before(
            series_id=series_id,
            as_of=cutoff,
            observed_start=start,
            observed_end=end,
        )
        latest_by_day: dict[str, dict[str, Any]] = {}
        for record in macro_records:
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("Macro PIT rates perdió artifact.")
            self._macro_repository.validate_record(record)
            observed = self._parse(artifact.get("observedAt"), "macro.observedAt")
            available = self._parse(artifact.get("availableAt"), "macro.availableAt")
            if observed > available or available > cutoff:
                raise RuntimeError("Macro rates contiene revisión futura.")
            day = observed.date().isoformat()
            current = latest_by_day.get(day)
            if current is None or self._parse(current["availableAt"], "macro.availableAt") < available:
                latest_by_day[day] = artifact

        matched_days = sorted(set(price_by_day) & set(latest_by_day))
        if len(matched_days) < self.MIN_PAIRED_CHANGES + 1:
            raise ValueError(
                f"Se requieren al menos {self.MIN_PAIRED_CHANGES + 1} fechas emparejadas PIT para rates."
            )

        returns: list[float] = []
        rate_changes: list[float] = []
        samples: list[dict[str, Any]] = []
        previous_day: str | None = None
        previous_price: float | None = None
        previous_rate: float | None = None
        for day in matched_days:
            price, market_observed, market_retrieved = price_by_day[day]
            macro = latest_by_day[day]
            rate = self._finite(macro.get("value"), "macro.value")
            if previous_day is not None and previous_price is not None and previous_rate is not None:
                asset_return = price / previous_price - 1.0
                rate_change = rate - previous_rate
                self._finite(asset_return, "asset_return")
                self._finite(rate_change, "rate_change")
                returns.append(asset_return)
                rate_changes.append(rate_change)
                samples.append(
                    {
                        "fromDate": previous_day,
                        "toDate": day,
                        "assetReturn": asset_return,
                        "rateChange": rate_change,
                        "marketObservedAt": market_observed,
                        "marketRetrievedAt": market_retrieved,
                        "macroObservationKey": str(macro.get("observationKey")),
                        "macroAvailableAt": str(macro.get("availableAt")),
                    }
                )
            previous_day = day
            previous_price = price
            previous_rate = rate

        if len(returns) < self.MIN_PAIRED_CHANGES:
            raise ValueError(f"Se requieren al menos {self.MIN_PAIRED_CHANGES} cambios emparejados para rates.")
        rates_exposure = self._correlation(returns, rate_changes)
        available_at = max(
            [self._parse(item["marketRetrievedAt"], "marketRetrievedAt") for item in samples]
            + [self._parse(item["macroAvailableAt"], "macroAvailableAt") for item in samples]
        )
        if available_at > cutoff:
            raise RuntimeError("Rates exposure contiene conocimiento posterior al as_of.")

        artifact: dict[str, Any] = {
            "module": "pit_rate_factor_exposure",
            "instrumentId": instrument_id,
            "marketSourceProvider": provider,
            "rateSeriesId": series_id,
            "periodStart": start.isoformat(),
            "periodEnd": end.isoformat(),
            "asOf": cutoff.isoformat(),
            "availableAt": available_at.isoformat(),
            "sampleCount": len(samples),
            "factors": {"rates": rates_exposure},
            "samples": samples,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "market_retrieved_and_macro_available_at_lte_as_of",
                "macroRevisionHandling": "latest_vintage_available_at_as_of_per_observed_date",
                "estimator": "pearson_correlation_asset_returns_vs_rate_changes_bounded_minus1_plus1",
                "frequency": "exact_observed_date_intersection_no_forward_fill",
                "thresholds": "not_calibrated",
                "missingEvidence": "fail_closed",
                "purpose": "factor_risk_diagnostic_only",
            },
        }
        artifact["factorExposureKey"] = self._key(artifact)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "pit_rate_factor_exposure":
            raise ValueError("Rates factor artifact tiene módulo inválido.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Rates factor artifact violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Rates factor artifact intentó habilitar producción/weighting.")
        count = artifact.get("sampleCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < self.MIN_PAIRED_CHANGES:
            raise ValueError("Rates factor artifact carece de muestra suficiente.")
        factors = artifact.get("factors")
        if not isinstance(factors, dict) or set(factors) != {"rates"}:
            raise ValueError("Rates factor artifact debe contener exclusivamente rates.")
        exposure = self._finite(factors["rates"], "factors.rates")
        if exposure < -1.0 - 1e-12 or exposure > 1.0 + 1e-12:
            raise ValueError("Rates factor debe permanecer en [-1,1].")
        as_of = self._parse(artifact.get("asOf"), "asOf")
        available = self._parse(artifact.get("availableAt"), "availableAt")
        if available > as_of:
            raise ValueError("Rates factor artifact viola PIT/no-lookahead.")
        samples = artifact.get("samples")
        if not isinstance(samples, list) or len(samples) != count:
            raise ValueError("Rates factor artifact perdió samples.")
        for sample in samples:
            if not isinstance(sample, dict):
                raise ValueError("Rates factor sample inválido.")
            self._finite(sample.get("assetReturn"), "sample.assetReturn")
            self._finite(sample.get("rateChange"), "sample.rateChange")
            key = str(sample.get("macroObservationKey") or "")
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                raise ValueError("Rates factor perdió Macro observationKey.")
            if self._parse(sample.get("macroAvailableAt"), "sample.macroAvailableAt") > as_of:
                raise ValueError("Rates factor sample contiene macro lookahead.")
            if self._parse(sample.get("marketRetrievedAt"), "sample.marketRetrievedAt") > as_of:
                raise ValueError("Rates factor sample contiene market lookahead.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise ValueError("Rates factor artifact perdió límite de trading.")
        if policy.get("thresholds") != "not_calibrated":
            raise ValueError("Rates factor artifact intentó calibrar umbrales sin evidencia.")
        expected = self._key(artifact)
        if str(artifact.get("factorExposureKey") or "") != expected:
            raise ValueError("factorExposureKey no coincide con rates artifact canónico.")
        return artifact

    @classmethod
    def _correlation(cls, x: list[float], y: list[float]) -> float:
        if len(x) != len(y) or len(x) < cls.MIN_PAIRED_CHANGES:
            raise ValueError("Muestra insuficiente para correlación rates.")
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        dx = [value - mean_x for value in x]
        dy = [value - mean_y for value in y]
        var_x = sum(value * value for value in dx)
        var_y = sum(value * value for value in dy)
        if var_x <= 1e-24 or var_y <= 1e-24:
            raise ValueError("Rates factor requiere variación suficiente en retornos y tipos.")
        result = sum(a * b for a, b in zip(dx, dy)) / math.sqrt(var_x * var_y)
        result = cls._finite(result, "rates")
        return max(-1.0, min(1.0, result))

    @staticmethod
    def _key(artifact: dict[str, Any]) -> str:
        canonical = {key: value for key, value in artifact.items() if key != "factorExposureKey"}
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _is_fmp(value: str) -> bool:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        return "financialmodelingprep" in normalized.replace(" ", "") or "financial modeling prep" in normalized or normalized.strip() == "fmp"

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
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser numérico finito.")
        return result

    @classmethod
    def _positive(cls, value: object, field: str) -> float:
        result = cls._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    @staticmethod
    def _utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse(cls, value: object, field: str) -> datetime:
        if isinstance(value, datetime):
            return cls._utc(value, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser timestamp ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._utc(parsed, field)
