from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.repositories.recommendation_shadow_frozen_candidate_repository import (
    RecommendationShadowFrozenCandidateRepository,
)
from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_holdout_gate_service import (
    RecommendationShadowHoldoutGateService,
)
from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)


class RecommendationShadowHoldoutPipelineService:
    """Evaluate one coherent persisted frozen-candidate cohort on fresh evidence.

    A holdout gate must never aggregate unrelated research experiments. Candidates
    are therefore grouped by the research-gate fingerprint *and* research cutoff.
    Only one coherent cohort is evaluated per call, and every persisted bundle is
    cryptographically revalidated before its frozen model reaches the holdout.
    """

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        repository: RecommendationShadowFrozenCandidateRepository | None = None,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
        holdout_service: RecommendationShadowIndependentHoldoutService | None = None,
        holdout_gate_service: RecommendationShadowHoldoutGateService | None = None,
    ) -> None:
        self._repository = repository or RecommendationShadowFrozenCandidateRepository()
        self._gated_freeze_service = gated_freeze_service or RecommendationShadowGatedFreezeService()
        self._holdout_service = holdout_service or RecommendationShadowIndependentHoldoutService()
        self._holdout_gate_service = holdout_gate_service or RecommendationShadowHoldoutGateService()

    def evaluate_latest_cohort(
        self,
        *,
        as_of: datetime,
        horizons: Iterable[int] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        requested = self._normalize_horizons(horizons)
        cohorts: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}

        for horizon in requested:
            for record in self._repository.list_for_horizon(horizon_days=horizon):
                bundle = record.get("bundle")
                if not isinstance(bundle, dict):
                    raise ValueError("El frozen candidate persistido no contiene bundle válido.")
                validated = self._gated_freeze_service.validate_bundle(bundle)
                self._assert_shadow(validated, "validated_bundle")
                research_cutoff = self._parse_utc(
                    validated.get("researchCutoff"), "researchCutoff"
                )
                if research_cutoff >= cutoff:
                    continue
                gate_fingerprint = self._required_text(
                    validated.get("researchGateFingerprint"), "researchGateFingerprint"
                )
                key = (gate_fingerprint, research_cutoff.isoformat())
                cohort = cohorts.setdefault(key, {})
                if horizon in cohort:
                    existing = cohort[horizon]
                    if existing.get("bundleFingerprint") != validated.get("bundleFingerprint"):
                        raise ValueError(
                            "Una misma cohorte contiene más de un candidato para el mismo horizonte."
                        )
                else:
                    cohort[horizon] = validated

        if not cohorts:
            return self._blocked(
                "shadow_holdout_no_eligible_frozen_cohort",
                asOf=cutoff.isoformat(),
                requestedHorizons=requested,
            )

        cohort_key = max(cohorts, key=lambda key: (self._parse_utc(key[1], "researchCutoff"), key[0]))
        gate_fingerprint, research_cutoff_iso = cohort_key
        candidates = cohorts[cohort_key]
        holdouts: dict[int, dict[str, Any]] = {}
        for horizon in requested:
            candidate = candidates.get(horizon)
            if candidate is None:
                holdouts[horizon] = self._missing_horizon(horizon)
                continue
            frozen_model = candidate.get("frozenModel")
            if not isinstance(frozen_model, dict):
                raise ValueError("El bundle validado no contiene frozenModel.")
            evidence = self._holdout_service.evaluate(
                frozen_model=frozen_model,
                as_of=cutoff,
            )
            self._assert_shadow(evidence, f"holdout_{horizon}")
            holdouts[horizon] = evidence

        gate = self._holdout_gate_service.evaluate(holdouts=holdouts)
        self._assert_shadow(gate, "holdout_gate")
        return {
            "status": "shadow_holdout_pipeline_evaluated",
            "researchGateFingerprint": gate_fingerprint,
            "researchCutoff": research_cutoff_iso,
            "asOf": cutoff.isoformat(),
            "requestedHorizons": requested,
            "persistedCandidateHorizons": sorted(candidates),
            "holdouts": holdouts,
            "holdoutGate": gate,
            "actionThresholdCalibrationResearchEligible": gate.get(
                "actionThresholdCalibrationResearchEligible"
            ) is True,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "cohortIdentity": "same_research_gate_fingerprint_and_research_cutoff",
                "persistedBundleRevalidation": True,
                "holdoutRefit": False,
                "crossExperimentAggregation": False,
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
            },
        }

    def _normalize_horizons(self, horizons: Iterable[int]) -> list[int]:
        values: list[int] = []
        seen: set[int] = set()
        for raw in horizons:
            try:
                horizon = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Los horizontes deben ser enteros positivos.") from exc
            if horizon <= 0:
                raise ValueError("Los horizontes deben ser enteros positivos.")
            if horizon in seen:
                raise ValueError("No se permiten horizontes duplicados.")
            seen.add(horizon)
            values.append(horizon)
        if not values:
            raise ValueError("Debe solicitarse al menos un horizonte.")
        return values

    def _missing_horizon(self, horizon: int) -> dict[str, Any]:
        return {
            "status": "frozen_candidate_missing_for_cohort",
            "horizonDays": horizon,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {"actions": "not_assigned", "automaticModelMutation": False},
        }

    def _blocked(self, status: str, **details: Any) -> dict[str, Any]:
        return {
            "status": status,
            **details,
            "actionThresholdCalibrationResearchEligible": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
            },
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_utc(self, value: object, field: str) -> datetime:
        raw = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)
