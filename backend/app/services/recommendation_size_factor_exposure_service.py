from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationSizeFactorExposureService:
    """Derive a bounded cross-sectional size diagnostic from PIT market caps."""

    MIN_UNIVERSE = 20

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()

    def evaluate(
        self,
        *,
        instrument_id: int,
        source_provider: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser entero positivo.")
        provider = self._text(source_provider, "source_provider")
        cutoff = self._utc(as_of, "as_of")
        rows = self._latest_caps(provider=provider, cutoff=cutoff)
        if len(rows) < self.MIN_UNIVERSE:
            raise ValueError(f"Se requieren al menos {self.MIN_UNIVERSE} instrumentos con market cap PIT.")

        by_id = {int(row["instrument_id"]): row for row in rows}
        if instrument_id not in by_id:
            raise ValueError("El instrumento no tiene market_cap_usd PIT verificable en el universo.")
        target = by_id[instrument_id]
        target_cap = self._positive(target["market_cap_usd"], "market_cap_usd")
        caps = sorted(self._positive(row["market_cap_usd"], "market_cap_usd") for row in rows)
        less = sum(value < target_cap for value in caps)
        equal = sum(value == target_cap for value in caps)
        average_rank = less + (equal - 1) / 2.0
        percentile = average_rank / (len(caps) - 1)
        size = self._finite(1.0 - 2.0 * percentile, "size")
        if size < -1.0 - 1e-12 or size > 1.0 + 1e-12:
            raise RuntimeError("El rank de size quedó fuera de [-1,1].")

        available = self._parse(target["retrieved_at"], "retrieved_at")
        observed = self._parse(target["observed_at"], "observed_at")
        if observed > available or available > cutoff:
            raise RuntimeError("Market cap target viola PIT/no-lookahead.")
        universe_available = max(self._parse(row["retrieved_at"], "retrieved_at") for row in rows)
        if universe_available > cutoff:
            raise RuntimeError("El universo de size contiene conocimiento futuro.")

        artifact: dict[str, Any] = {
            "module": "pit_size_factor_exposure",
            "instrumentId": instrument_id,
            "sourceProvider": provider,
            "asOf": cutoff.isoformat(),
            "availableAt": universe_available.isoformat(),
            "marketCapUsd": target_cap,
            "universeCount": len(rows),
            "factors": {"size": size},
            "provenance": {
                "targetObservedAt": observed.isoformat(),
                "targetRetrievedAt": available.isoformat(),
                "universeRule": "latest_pit_market_cap_per_instrument_same_provider",
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_and_retrieved_at_lte_as_of",
                "estimator": "cross_sectional_market_cap_rank_small_positive_large_negative_bounded_minus1_plus1",
                "universe": "same_provider_instruments_with_positive_pit_market_cap",
                "thresholds": "not_calibrated",
                "missingEvidence": "fail_closed",
                "purpose": "factor_risk_diagnostic_only",
            },
        }
        artifact["factorExposureKey"] = self._key(artifact)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "pit_size_factor_exposure":
            raise ValueError("Size factor artifact tiene módulo inválido.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Size factor artifact violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Size factor artifact intentó habilitar producción/weighting.")
        count = artifact.get("universeCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < self.MIN_UNIVERSE:
            raise ValueError("Size factor artifact carece de universo suficiente.")
        factors = artifact.get("factors")
        if not isinstance(factors, dict) or set(factors) != {"size"}:
            raise ValueError("Size factor artifact debe contener exclusivamente size.")
        size = self._finite(factors["size"], "factors.size")
        if size < -1.0 - 1e-12 or size > 1.0 + 1e-12:
            raise ValueError("Size factor debe permanecer en [-1,1].")
        as_of = self._parse(artifact.get("asOf"), "asOf")
        available = self._parse(artifact.get("availableAt"), "availableAt")
        if available > as_of:
            raise ValueError("Size factor artifact viola PIT/no-lookahead.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False or policy.get("thresholds") != "not_calibrated":
            raise ValueError("Size factor artifact perdió límites de seguridad/calibración.")
        expected = self._key(artifact)
        if str(artifact.get("factorExposureKey") or "") != expected:
            raise ValueError("factorExposureKey no coincide con size artifact canónico.")
        return artifact

    def _latest_caps(self, *, provider: str, cutoff: datetime) -> list[dict[str, Any]]:
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT instrument_id, market_cap_usd, observed_at, retrieved_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY instrument_id
                               ORDER BY observed_at DESC, id DESC
                           ) AS rn
                    FROM market_observations
                    WHERE source_provider = ?
                      AND market_cap_usd IS NOT NULL
                      AND market_cap_usd > 0
                      AND observed_at <= ?
                      AND retrieved_at <= ?
                )
                SELECT instrument_id, market_cap_usd, observed_at, retrieved_at
                FROM ranked
                WHERE rn = 1
                ORDER BY instrument_id ASC
                """,
                (provider, cutoff.isoformat(), cutoff.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def _key(self, artifact: dict[str, Any]) -> str:
        canonical = {key: value for key, value in artifact.items() if key != "factorExposureKey"}
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        normalized = text.casefold().replace("_", " ").replace("-", " ")
        if "financialmodelingprep" in normalized.replace(" ", "") or "financial modeling prep" in normalized:
            raise ValueError("FMP no está permitido como source_provider.")
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
