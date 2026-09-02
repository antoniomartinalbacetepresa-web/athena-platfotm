from __future__ import annotations

from datetime import datetime
from typing import Any

from app.repositories.recommendation_shadow_frozen_candidate_repository import (
    RecommendationShadowFrozenCandidateRepository,
)
from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_live_cycle_service import (
    RecommendationShadowLiveCycleService,
)


class RecommendationShadowPersistedLiveCycleService:
    """Trusted live-shadow entry point backed by persisted frozen candidates.

    A caller supplies only bundle fingerprints. The corresponding immutable
    bundle JSON is loaded from SQLite and revalidated before any current PIT
    evidence is captured or any prediction is produced. This keeps self-consistent
    caller-built JSON from being mistaken for stored research provenance.
    """

    def __init__(
        self,
        *,
        frozen_repository: RecommendationShadowFrozenCandidateRepository | None = None,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
        live_cycle_service: RecommendationShadowLiveCycleService | None = None,
    ) -> None:
        self._frozen_repository = (
            frozen_repository or RecommendationShadowFrozenCandidateRepository()
        )
        self._gated_freeze_service = (
            gated_freeze_service or RecommendationShadowGatedFreezeService()
        )
        self._live_cycle_service = live_cycle_service or RecommendationShadowLiveCycleService()

    def run(
        self,
        *,
        symbol: str,
        as_of: datetime,
        bundle_fingerprints: list[str],
        benchmark_symbol: str,
        captured_at: datetime | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]:
        fingerprints = self._fingerprints(bundle_fingerprints)
        bundles: list[dict[str, Any]] = []
        seen_horizons: set[int] = set()
        for fingerprint in fingerprints:
            row = self._frozen_repository.get_by_fingerprint(fingerprint)
            if row is None:
                raise ValueError(
                    f"No existe frozen candidate persistido para {fingerprint}."
                )
            stored_fingerprint = str(row.get("bundle_fingerprint") or "").lower()
            if stored_fingerprint != fingerprint:
                raise RuntimeError("El repositorio devolvió otro bundle fingerprint.")
            bundle = row.get("bundle")
            if not isinstance(bundle, dict):
                raise ValueError("El frozen candidate persistido carece de bundle válido.")
            validated = self._gated_freeze_service.validate_bundle(bundle)
            self._assert_shadow(validated)
            if str(validated.get("bundleFingerprint") or "").lower() != fingerprint:
                raise ValueError("El bundle persistido no coincide con su clave de repositorio.")
            horizon = int(validated.get("horizonDays", 0))
            if horizon <= 0:
                raise ValueError("El frozen candidate persistido tiene horizonte inválido.")
            if horizon in seen_horizons:
                raise ValueError("No puede haber dos frozen candidates para el mismo horizonte.")
            seen_horizons.add(horizon)
            bundles.append(validated)

        result = self._live_cycle_service.run(
            symbol=symbol,
            as_of=as_of,
            gated_bundles=bundles,
            benchmark_symbol=benchmark_symbol,
            captured_at=captured_at,
            horizons=horizons,
        )
        self._assert_cycle_shadow(result)
        return {
            **result,
            "frozenCandidateSource": "sqlite_persisted_and_revalidated",
            "bundleFingerprints": fingerprints,
            "policy": {
                **dict(result.get("policy") or {}),
                "callerSuppliedFrozenBundleJsonTrusted": False,
                "frozenBundleLookup": "exact_persisted_sha256_fingerprint",
                "frozenBundleIntegrity": "gated_freeze_revalidated_after_load",
            },
        }

    def _fingerprints(self, values: list[str]) -> list[str]:
        if not isinstance(values, list) or not values:
            raise ValueError("bundle_fingerprints debe contener al menos un fingerprint.")
        result: list[str] = []
        for raw in values:
            value = str(raw or "").strip().lower()
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("Cada bundle fingerprint debe ser SHA-256 hexadecimal.")
            result.append(value)
        if len(set(result)) != len(result):
            raise ValueError("Los bundle fingerprints no pueden repetirse.")
        return result

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError("El frozen bundle debe mantener productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El frozen bundle debe mantener advisoryStatus=no_advice.")

    def _assert_cycle_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError("El ciclo live debe mantener productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El ciclo live debe mantener advisoryStatus=no_advice.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El ciclo live no puede habilitar recomendaciones.")
