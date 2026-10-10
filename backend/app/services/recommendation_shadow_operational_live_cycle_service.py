from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_frozen_candidate_repository import (
    RecommendationShadowFrozenCandidateRepository,
)
from app.services.recommendation_shadow_persisted_live_cycle_service import (
    RecommendationShadowPersistedLiveCycleService,
)


class RecommendationShadowOperationalLiveCycleService:
    """Select a coherent persisted frozen cohort and run the live shadow cycle.

    The operational path never accepts caller-supplied frozen bundle JSON or
    manually chosen fingerprints. It discovers immutable bundles already stored
    by ATHENA, groups them by the exact research gate and cutoff that produced
    them, and selects the most recent complete cohort that was knowable at the
    requested ``as_of``. Each selected bundle is revalidated again by the
    persisted live-cycle service before current PIT evidence is captured.
    """

    def __init__(
        self,
        *,
        frozen_repository: RecommendationShadowFrozenCandidateRepository | None = None,
        persisted_live_cycle_service: RecommendationShadowPersistedLiveCycleService | None = None,
    ) -> None:
        self._frozen_repository = (
            frozen_repository or RecommendationShadowFrozenCandidateRepository()
        )
        self._persisted_live_cycle_service = (
            persisted_live_cycle_service or RecommendationShadowPersistedLiveCycleService(
                frozen_repository=self._frozen_repository
            )
        )

    def run(
        self,
        *,
        symbol: str,
        as_of: datetime,
        benchmark_symbol: str,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
        captured_at: datetime | None = None,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        requested_horizons = self._horizons(horizons)
        normalized_symbol = self._symbol(symbol, "symbol")
        normalized_benchmark = self._symbol(benchmark_symbol, "benchmark_symbol")

        cohorts: dict[tuple[str, str], dict[int, list[dict[str, Any]]]] = {}
        cohort_cutoffs: dict[tuple[str, str], datetime] = {}
        for horizon in requested_horizons:
            for row in self._frozen_repository.list_for_horizon(horizon_days=horizon):
                gate_fingerprint = str(row.get("research_gate_fingerprint") or "").lower()
                research_cutoff_raw = row.get("research_cutoff")
                if not self._sha256(gate_fingerprint):
                    raise ValueError("Frozen candidate persistido con research gate inválida.")
                research_cutoff = self._parse_aware_utc(
                    research_cutoff_raw, "research_cutoff"
                )
                if research_cutoff > cutoff:
                    continue
                key = (gate_fingerprint, research_cutoff.isoformat())
                cohort_cutoffs[key] = research_cutoff
                cohorts.setdefault(key, {}).setdefault(horizon, []).append(row)

        complete_keys = [
            key
            for key, members in cohorts.items()
            if all(horizon in members for horizon in requested_horizons)
        ]
        if not complete_keys:
            return self._blocked(
                reason="no_complete_persisted_frozen_cohort",
                symbol=normalized_symbol,
                benchmark_symbol=normalized_benchmark,
                as_of=cutoff,
                horizons=requested_horizons,
            )

        selected_key = max(
            complete_keys,
            key=lambda key: (cohort_cutoffs[key], key[0]),
        )
        selected_members = cohorts[selected_key]
        ambiguous = [
            horizon
            for horizon in requested_horizons
            if len(selected_members[horizon]) != 1
        ]
        if ambiguous:
            raise ValueError(
                "La cohorte frozen seleccionada es ambigua para horizontes: "
                + ", ".join(str(value) for value in ambiguous)
                + "."
            )

        fingerprints: list[str] = []
        for horizon in requested_horizons:
            row = selected_members[horizon][0]
            fingerprint = str(row.get("bundle_fingerprint") or "").lower()
            if not self._sha256(fingerprint):
                raise ValueError("Frozen candidate persistido con bundle fingerprint inválido.")
            fingerprints.append(fingerprint)

        result = self._persisted_live_cycle_service.run(
            symbol=normalized_symbol,
            as_of=cutoff,
            bundle_fingerprints=fingerprints,
            benchmark_symbol=normalized_benchmark,
            captured_at=captured_at,
            horizons=requested_horizons,
        )
        self._assert_shadow(result)
        return {
            **result,
            "frozenCohortSelection": {
                "mode": "latest_complete_persisted_cohort_known_at_as_of",
                "researchGateFingerprint": selected_key[0],
                "researchCutoff": selected_key[1],
                "horizons": list(requested_horizons),
                "bundleFingerprints": fingerprints,
            },
            "policy": {
                **dict(result.get("policy") or {}),
                "manualBundleFingerprintSelection": False,
                "crossResearchGateCohortMixing": False,
                "futureResearchCutoffSelection": False,
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
        }

    def _blocked(
        self,
        *,
        reason: str,
        symbol: str,
        benchmark_symbol: str,
        as_of: datetime,
        horizons: tuple[int, ...],
    ) -> dict[str, Any]:
        return {
            "status": "shadow_operational_live_cycle_blocked",
            "reason": reason,
            "symbol": symbol,
            "benchmarkSymbol": benchmark_symbol,
            "asOf": as_of.isoformat(),
            "horizons": list(horizons),
            "policy": {
                "completeFrozenCohortRequired": True,
                "manualBundleFingerprintSelection": False,
                "crossResearchGateCohortMixing": False,
                "futureResearchCutoffSelection": False,
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
        }

    def _horizons(self, values: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        horizons = tuple(int(value) for value in values)
        if not horizons or any(value <= 0 for value in horizons):
            raise ValueError("horizons debe contener enteros positivos.")
        if len(set(horizons)) != len(horizons):
            raise ValueError("horizons no puede contener duplicados.")
        return horizons

    def _symbol(self, value: str, field: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _parse_aware_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} persistido es obligatorio.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} persistido no es ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _sha256(self, value: str) -> bool:
        return len(value) == 64 and all(char in "0123456789abcdef" for char in value)

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise RuntimeError("El live cycle persistido violó no_advice.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("El live cycle persistido intentó habilitar producción.")
        if payload.get("recommendationCandidateReady") is not False:
            raise RuntimeError("El live cycle persistido intentó habilitar recomendación.")
