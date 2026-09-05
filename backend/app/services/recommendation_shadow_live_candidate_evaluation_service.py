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
    """Evaluate persisted continuous predictions using only matured PIT outcomes.

    Excess-return predictions are scored only against outcomes whose benchmark
    leg retains the exact frozen-symbol observation provenance. Persisted return
    scalars are also cross-checked so storage corruption cannot silently alter
    longitudinal OOS evidence.
    """

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

    def evaluate(self, *, candidate_id: int, as_of: datetime) -> dict[str, Any]:
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
        frozen_benchmark_symbol = self._optional_symbol(snapshot.get("benchmark_symbol"))

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
        seen_candidate_horizons: set[int] = set()
        for key, inference in expected_horizons.items():
            if not isinstance(inference, dict):
                raise ValueError("Un horizonte del candidato tiene formato inválido.")
            try:
                key_horizon = int(key)
                horizon = int(inference.get("horizonDays"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Un horizonte del candidato no es entero.") from exc
            if horizon <= 0 or key_horizon != horizon:
                raise ValueError("La identidad de horizonte del candidato es inconsistente.")
            if horizon in seen_candidate_horizons:
                raise ValueError("El candidato contiene un horizonte duplicado.")
            seen_candidate_horizons.add(horizon)

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
            evaluated_at = self._parse_aware(outcome.get("evaluated_at"), "outcome.evaluated_at")
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
            benchmark_evidence = self._validated_benchmark_evidence(
                outcome,
                frozen_symbol=frozen_benchmark_symbol,
                due_at=due_at,
                evaluated_at=evaluated_at,
            )
            realized = self._required_finite(outcome.get("excess_return"), "outcome.excess_return")
            stored_realized_return = self._required_finite(
                outcome.get("realized_return"), "outcome.realized_return"
            )
            stored_benchmark_return = self._required_finite(
                outcome.get("benchmark_return"), "outcome.benchmark_return"
            )
            recomputed_excess_return = stored_realized_return - stored_benchmark_return
            if not math.isclose(
                realized,
                recomputed_excess_return,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "outcome.excess_return no coincide con realized_return - benchmark_return."
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
                "benchmarkReturn": stored_benchmark_return,
                "realizedReturn": stored_realized_return,
                "benchmarkEvidence": benchmark_evidence,
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
            "frozenBenchmarkSymbol": frozen_benchmark_symbol,
            "evaluatedHorizonCount": evaluated_count,
            "metrics": metrics,
            "horizons": horizon_results,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "lookAhead": "outcome_evaluated_at_must_not_exceed_as_of",
                "target": "realized_excess_return_vs_frozen_snapshot_benchmark",
                "targetProvenance": "exact_persisted_benchmark_observations_required",
                "targetIntegrity": "persisted_excess_return_must_equal_realized_return_minus_benchmark_return",
                "predictions": "immutable_persisted_live_candidate",
                "actions": "not_evaluated_not_assigned",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
            },
        }

    def _validated_benchmark_evidence(
        self,
        outcome: dict[str, Any],
        *,
        frozen_symbol: str | None,
        due_at: datetime,
        evaluated_at: datetime,
    ) -> dict[str, Any]:
        if frozen_symbol is None:
            raise ValueError(
                "Un candidato de exceso de rentabilidad requiere benchmark congelado."
            )
        evidence = outcome.get("benchmark_evidence")
        if not isinstance(evidence, dict) or evidence.get("status") != "resolved":
            raise ValueError(
                "El outcome carece de evidencia trazable del benchmark congelado."
            )
        symbol = self._optional_symbol(evidence.get("benchmarkSymbol"))
        if symbol != frozen_symbol:
            raise ValueError("El outcome usa evidencia de otro benchmark.")
        instrument_id = evidence.get("benchmarkInstrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("La evidencia del benchmark carece de instrumento válido.")
        entry_price = self._required_finite(evidence.get("entryPrice"), "benchmark.entryPrice")
        exit_price = self._required_finite(evidence.get("exitPrice"), "benchmark.exitPrice")
        if entry_price <= 0 or exit_price <= 0:
            raise ValueError("Los precios preservados del benchmark deben ser positivos.")
        recomputed = (exit_price / entry_price) - 1.0
        evidence_return = self._required_finite(
            evidence.get("benchmarkReturn"), "benchmark.benchmarkReturn"
        )
        stored_return = self._required_finite(
            outcome.get("benchmark_return"), "outcome.benchmark_return"
        )
        if not math.isclose(recomputed, evidence_return, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("La evidencia del benchmark no reproduce su rentabilidad.")
        if not math.isclose(stored_return, evidence_return, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("La rentabilidad benchmark persistida no coincide con su evidencia.")

        exit_observed = self._parse_aware(
            evidence.get("exitObservedAt"), "benchmark.exitObservedAt"
        )
        entry_retrieved = self._parse_aware(
            evidence.get("entryRetrievedAt"), "benchmark.entryRetrievedAt"
        )
        exit_retrieved = self._parse_aware(
            evidence.get("exitRetrievedAt"), "benchmark.exitRetrievedAt"
        )
        if exit_observed < due_at or exit_observed > evaluated_at:
            raise ValueError("La salida del benchmark está fuera de la ventana del outcome.")
        if entry_retrieved > evaluated_at or exit_retrieved > evaluated_at:
            raise ValueError("La evidencia benchmark fue conocida después de evaluated_at.")
        entry_observed = self._parse_aware(
            evidence.get("entryObservedAt"), "benchmark.entryObservedAt"
        )
        entry_provider = str(evidence.get("entrySourceProvider") or "").strip()
        exit_provider = str(evidence.get("exitSourceProvider") or "").strip()
        if not entry_provider or not exit_provider:
            raise ValueError("La evidencia benchmark carece de provenance de proveedor.")
        return {
            "benchmarkSymbol": frozen_symbol,
            "benchmarkInstrumentId": instrument_id,
            "entryPrice": entry_price,
            "exitPrice": exit_price,
            "entryObservedAt": entry_observed.isoformat(),
            "exitObservedAt": exit_observed.isoformat(),
            "entryRetrievedAt": entry_retrieved.isoformat(),
            "exitRetrievedAt": exit_retrieved.isoformat(),
            "entrySourceProvider": entry_provider,
            "exitSourceProvider": exit_provider,
        }

    def _assert_shadow(self, candidate: dict[str, Any]) -> None:
        if candidate.get("productionEligible") is not False:
            raise ValueError("El candidato evaluado debe mantener productionEligible=False.")
        if candidate.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato evaluado debe mantener no_advice.")
        if candidate.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato evaluado no puede habilitar recomendación.")

    def _optional_symbol(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

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
