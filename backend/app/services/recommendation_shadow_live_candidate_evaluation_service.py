from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class RecommendationShadowLiveCandidateEvaluationService:
    """Evaluate persisted continuous predictions using only matured PIT outcomes."""

    def __init__(
        self,
        *,
        candidate_repository: RecommendationShadowLiveCandidateRepository | None = None,
        snapshot_repository: RecommendationShadowRepository | None = None,
        candidate_service: RecommendationShadowLiveCandidateService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._snapshot_repository = snapshot_repository or RecommendationShadowRepository()
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()

    def evaluate(
        self,
        *,
        candidate_id: int,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        stored = self._candidate_repository.get(candidate_id)
        if stored is None:
            raise ValueError("El candidato shadow live no existe.")
        artifact = stored.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("El candidato persistido carece de artefacto válido.")
        candidate = self._candidate_service.validate_artifact(artifact)
        self._assert_shadow(candidate)

        snapshot_id = int(stored.get("snapshot_id", 0))
        if snapshot_id <= 0:
            raise ValueError("El candidato persistido carece de snapshot_id válido.")
        snapshot = self._snapshot_repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError("El snapshot PIT asociado al candidato ya no existe.")

        candidate_as_of = self._parse_aware(candidate.get("asOf"), "candidate.asOf")
        if cutoff < candidate_as_of:
            raise ValueError("as_of no puede ser anterior al candidato persistido.")
        outcomes = self._snapshot_repository.list_outcomes(snapshot_id)
        outcome_by_horizon: dict[int, dict[str, Any]] = {}
        for outcome in outcomes:
            horizon = int(outcome.get("horizon_days", 0))
            if horizon <= 0:
                raise ValueError("Existe un outcome con horizonte inválido.")
            if horizon in outcome_by_horizon:
                raise ValueError("Existe más de un outcome persistido para el mismo horizonte.")
            outcome_by_horizon[horizon] = outcome

        horizon_results: dict[str, dict[str, Any]] = {}
        errors: list[float] = []
        direction_hits: list[bool] = []
        expected_horizons = candidate.get("horizons")
        if not isinstance(expected_horizons, dict):
            raise ValueError("El candidato carece de horizontes de inferencia.")
        for key, inference in expected_horizons.items():
            if not isinstance(inference, dict):
                raise ValueError("Un horizonte del candidato tiene formato inválido.")
            horizon = int(inference.get("horizonDays", key))
            expected = self._optional_finite(inference.get("expectedExcessReturn"))
            if expected is None:
                horizon_results[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "not_evaluable_no_live_prediction",
                    "expectedExcessReturn": None,
                }
                continue

            outcome = outcome_by_horizon.get(horizon)
            if outcome is None:
                horizon_results[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "pending_outcome",
                    "expectedExcessReturn": expected,
                }
                continue
            evaluated_at = self._parse_aware(
                outcome.get("evaluated_at"), "outcome.evaluated_at"
            )
            if evaluated_at > cutoff:
                horizon_results[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "pending_outcome_not_mature_at_as_of",
                    "expectedExcessReturn": expected,
                    "outcomeEvaluatedAt": evaluated_at.isoformat(),
                }
                continue
            due_at = self._parse_aware(outcome.get("due_at"), "outcome.due_at")
            if evaluated_at < due_at:
                raise ValueError("Un outcome fue evaluado antes de su vencimiento.")
            realized = self._required_finite(
                outcome.get("excess_return"), "outcome.excess_return"
            )
            error = expected - realized
            if not math.isfinite(error):
                raise ValueError("El error de predicción no es finito.")
            direction_correct = (expected >= 0.0) == (realized >= 0.0)
            errors.append(error)
            direction_hits.append(direction_correct)
            horizon_results[str(horizon)] = {
                "horizonDays": horizon,
                "status": "evaluated",
                "expectedExcessReturn": expected,
                "realizedExcessReturn": realized,
                "predictionError": error,
                "absoluteError": abs(error),
                "squaredError": error * error,
                "directionCorrect": direction_correct,
                "outcomeDueAt": due_at.isoformat(),
                "outcomeEvaluatedAt": evaluated_at.isoformat(),
                "benchmarkReturn": self._optional_finite(outcome.get("benchmark_return")),
                "realizedReturn": self._optional_finite(outcome.get("realized_return")),
            }

        evaluated_count = len(errors)
        metrics = (
            {
                "mse": sum(error * error for error in errors) / evaluated_count,
                "mae": sum(abs(error) for error in errors) / evaluated_count,
                "signAccuracy": sum(1 for hit in direction_hits if hit) / evaluated_count,
            }
            if evaluated_count > 0
            else None
        )
        return {
            "status": (
                "shadow_live_candidate_outcomes_evaluated"
                if evaluated_count > 0
                else "shadow_live_candidate_outcomes_pending"
            ),
            "candidateId": candidate_id,
            "candidateFingerprint": candidate.get("candidateFingerprint"),
            "snapshotId": snapshot_id,
            "symbol": candidate.get("symbol"),
            "candidateAsOf": candidate_as_of.isoformat(),
            "asOf": cutoff.isoformat(),
            "evaluatedHorizonCount": evaluated_count,
            "metrics": metrics,
            "horizons": horizon_results,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "lookAhead": "outcome_evaluated_at_must_not_exceed_as_of",
                "target": "realized_excess_return_vs_frozen_snapshot_benchmark",
                "predictions": "immutable_persisted_live_candidate",
                "actions": "not_evaluated_not_assigned",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
            },
        }

    def _assert_shadow(self, candidate: dict[str, Any]) -> None:
        if candidate.get("productionEligible") is not False:
            raise ValueError("El candidato evaluado debe mantener productionEligible=False.")
        if candidate.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato evaluado debe mantener no_advice.")
        if candidate.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato evaluado no puede habilitar recomendación.")

    def _optional_finite(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _required_finite(self, value: object, field: str) -> float:
        parsed = self._optional_finite(value)
        if parsed is None:
            raise ValueError(f"{field} debe ser finito.")
        return parsed

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
