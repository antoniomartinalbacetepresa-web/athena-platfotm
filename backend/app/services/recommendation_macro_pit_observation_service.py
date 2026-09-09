from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_PROVIDERS = {"fred_alfred", "ecb", "bls", "world_bank"}


class RecommendationMacroPitObservationService:
    """Build and validate immutable point-in-time macro observations.

    Macro data may be revised after first publication. ATHENA therefore separates
    the economic observation timestamp from the timestamp at which that value was
    actually available. Downstream research must filter by ``availableAt`` and
    never substitute a later revision into an earlier decision point.
    """

    def build_artifact(
        self,
        *,
        series_id: str,
        value: float,
        observed_at: datetime,
        available_at: datetime,
        source_provider: str,
        source_ref: str,
        unit: str,
    ) -> dict[str, Any]:
        normalized_series = self._text(series_id, "series_id").upper()
        provider = self._provider(source_provider)
        ref = self._text(source_ref, "source_ref")
        normalized_unit = self._text(unit, "unit")
        numeric = self._finite(value, "value")
        observed = self._aware_utc(observed_at, "observed_at")
        available = self._aware_utc(available_at, "available_at")
        if observed > available:
            raise ValueError("observed_at no puede ser posterior a available_at.")

        canonical = {
            "seriesId": normalized_series,
            "value": format(numeric, ".17g"),
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "sourceProvider": provider,
            "sourceRef": ref,
            "unit": normalized_unit,
        }
        observation_key = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        artifact: dict[str, Any] = {
            "module": "macro_pit_observation",
            "observationKey": observation_key,
            "seriesId": normalized_series,
            "value": numeric,
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "sourceProvider": provider,
            "sourceRef": ref,
            "unit": normalized_unit,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_at_lte_available_at",
                "revisionHandling": "vintages_preserved_never_backfilled_into_prior_as_of",
                "finiteData": "required",
                "provenance": "source_provider_and_source_ref_required",
                "identity": "deterministic_sha256",
                "purpose": "historical_macro_evidence_only",
            },
        }
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "macro_pit_observation":
            raise ValueError("Macro PIT artifact tiene módulo inválido.")
        key = str(artifact.get("observationKey") or "").strip().lower()
        if _SHA256_RE.fullmatch(key) is None:
            raise ValueError("observationKey debe ser SHA-256 hexadecimal válido.")
        series_id = self._text(artifact.get("seriesId"), "seriesId").upper()
        value = self._finite(artifact.get("value"), "value")
        observed = self._parse_datetime(artifact.get("observedAt"), "observedAt")
        available = self._parse_datetime(artifact.get("availableAt"), "availableAt")
        if observed > available:
            raise ValueError("observedAt no puede ser posterior a availableAt.")
        provider = self._provider(artifact.get("sourceProvider"))
        source_ref = self._text(artifact.get("sourceRef"), "sourceRef")
        unit = self._text(artifact.get("unit"), "unit")

        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Macro PIT artifact violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Macro PIT artifact intentó habilitar producción/weighting.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Macro PIT artifact perdió policy.")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Macro PIT artifact intentó habilitar automatización.")
        if policy.get("revisionHandling") != "vintages_preserved_never_backfilled_into_prior_as_of":
            raise ValueError("Macro PIT artifact perdió política anti-lookahead de revisiones.")

        canonical = {
            "seriesId": series_id,
            "value": format(value, ".17g"),
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "sourceProvider": provider,
            "sourceRef": source_ref,
            "unit": unit,
        }
        expected = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if key != expected:
            raise ValueError("Macro PIT artifact no coincide con su observationKey canónica.")
        return artifact

    @staticmethod
    def _text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} es obligatorio.")
        return value.strip()

    @classmethod
    def _provider(cls, value: object) -> str:
        provider = cls._text(value, "sourceProvider").lower()
        if provider == "fmp" or "financialmodelingprep" in provider:
            raise ValueError("FMP está prohibido como fuente de Macro PIT.")
        if provider not in _ALLOWED_PROVIDERS:
            raise ValueError("sourceProvider macro no está autorizado.")
        return provider

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico y finito.")
        try:
            numeric = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico y finito.") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"{field} debe ser numérico y finito.")
        return numeric

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, value: object, field: str) -> datetime:
        if isinstance(value, datetime):
            return cls._aware_utc(value, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser timestamp ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._aware_utc(parsed, field)
