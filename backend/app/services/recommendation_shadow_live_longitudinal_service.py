from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class _CandidateRepository(Protocol):
    def list_all(self) -> list[dict[str, Any]]: ...


class _EvaluationService(Protocol):
    def evaluate(self, *, candidate_id: int, as_of: datetime) -> dict[str, Any]: ...


class _CandidateService(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowLiveLongitudinalService:
    """Measure immutable live-shadow predictions across time without advice.

    Metrics are never pooled across different frozen-model fingerprints. A model
    revision creates a new longitudinal series even when the horizon is the same,
    preventing an apparently stable aggregate from hiding model drift. Only
    outcomes already matured and persisted by ``as_of`` are included.
    """

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        evaluation_service: _EvaluationService | None = None,
        candidate_service: _CandidateService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._evaluation_service = (
            evaluation_service or RecommendationShadowLiveCandidateEvaluationService()
        )
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()

    def evaluate(
        self,
        *,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        requested_horizons = self._horizons(horizons)
        normalized_symbol = str(symbol or "").strip().upper() or None

        series: dict[int, dict[str, list[dict[str, Any]]]] = {
            horizon: {} for horizon in requested_horizons
        }
        candidate_count = 0
        eligible_candidate_count = 0
        evaluated_candidate_count = 0
        skipped_future_candidate_count = 0
        seen_candidate_fingerprints: set[str] = set()

        for stored in self._candidate_repository.list_all():
            candidate_id = self._positive_int(stored.get("id"), "candidate.id")
            artifact = stored.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("Un candidato live persistido carece de artefacto válido.")
            candidate = self._candidate_service.validate_artifact(artifact)
            self._assert_candidate_shadow(candidate)

            fingerprint = self._required_text(
                candidate.get("candidateFingerprint"), "candidateFingerprint"
            )
            stored_fingerprint = self._required_text(
                stored.get("candidate_fingerprint"), "stored.candidate_fingerprint"
            )
            if fingerprint != stored_fingerprint:
                raise ValueError("El fingerprint persistido no coincide con el artefacto live.")
            if fingerprint in seen_candidate_fingerprints:
                raise ValueError("Existe un candidateFingerprint duplicado en persistencia.")
            seen_candidate_fingerprints.add(fingerprint)
            candidate_count += 1

            candidate_symbol = self._required_text(candidate.get("symbol"), "candidate.symbol").upper()
            if normalized_symbol is not None and candidate_symbol != normalized_symbol:
                continue
            candidate_as_of = self._parse_aware(candidate.get("asOf"), "candidate.asOf")
            if candidate_as_of > cutoff:
                skipped_future_candidate_count += 1
                continue
            eligible_candidate_count += 1

            evaluation = self._evaluation_service.evaluate(
                candidate_id=candidate_id,
                as_of=cutoff,
            )
            self._assert_evaluation_shadow(evaluation)
            if self._required_text(
                evaluation.get("candidateFingerprint"), "evaluation.candidateFingerprint"
            ) != fingerprint:
                raise ValueError("La evaluación longitudinal cambió el candidato de referencia.")
            if self._required_text(evaluation.get("symbol"), "evaluation.symbol").upper() != candidate_symbol:
                raise ValueError("La evaluación longitudinal cambió el símbolo del candidato.")

            evaluated_any = False
            candidate_horizons = candidate.get("horizons")
            evaluated_horizons = evaluation.get("horizons")
            if not isinstance(candidate_horizons, dict) or not isinstance(evaluated_horizons, dict):
                raise ValueError("El candidato o su evaluación carecen de horizontes válidos.")

            for horizon in requested_horizons:
                inference = candidate_horizons.get(str(horizon))
                outcome = evaluated_horizons.get(str(horizon))
                if inference is None or outcome is None:
                    continue
                if not isinstance(inference, dict) or not isinstance(outcome, dict):
                    raise ValueError("Un horizonte longitudinal tiene formato inválido.")
                if outcome.get("status") != "evaluated":
                    continue
                expected = self._required_finite(
                    outcome.get("expectedExcessReturn"), "expectedExcessReturn"
                )
                realized = self._required_finite(
                    outcome.get("realizedExcessReturn"), "realizedExcessReturn"
                )
                model_fingerprint = self._required_sha256(
                    inference.get("modelFingerprint"), "modelFingerprint"
                )
                confirmation_fingerprint = self._required_sha256(
                    candidate.get("confirmationEvidenceFingerprint"),
                    "confirmationEvidenceFingerprint",
                )
                series[horizon].setdefault(model_fingerprint, []).append(
                    {
                        "candidateId": candidate_id,
                        "candidateFingerprint": fingerprint,
                        "confirmationEvidenceFingerprint": confirmation_fingerprint,
                        "candidateAsOf": candidate_as_of.isoformat(),
                        "expectedExcessReturn": expected,
                        "realizedExcessReturn": realized,
                        "predictionError": expected - realized,
                    }
                )
                evaluated_any = True
            if evaluated_any:
                evaluated_candidate_count += 1

        horizon_payloads: dict[str, dict[str, Any]] = {}
        evaluated_observation_count = 0
        for horizon in requested_horizons:
            models: dict[str, dict[str, Any]] = {}
            horizon_observations = 0
            for model_fingerprint, observations in sorted(series[horizon].items()):
                metrics = self._metrics(observations)
                models[model_fingerprint] = {
                    "modelFingerprint": model_fingerprint,
                    "observationCount": len(observations),
                    "metrics": metrics,
                    "firstCandidateAsOf": min(
                        item["candidateAsOf"] for item in observations
                    ),
                    "lastCandidateAsOf": max(
                        item["candidateAsOf"] for item in observations
                    ),
                    "distinctConfirmationEvidenceCount": len(
                        {
                            item["confirmationEvidenceFingerprint"]
                            for item in observations
                        }
                    ),
                }
                horizon_observations += len(observations)
            evaluated_observation_count += horizon_observations
            distinct_models = len(models)
            horizon_payloads[str(horizon)] = {
                "horizonDays": horizon,
                "evaluatedObservationCount": horizon_observations,
                "distinctModelCount": distinct_models,
                "comparabilityStatus": (
                    "single_frozen_model_series"
                    if distinct_models == 1
                    else "mixed_model_versions_not_pooled"
                    if distinct_models > 1
                    else "no_mature_live_evidence"
                ),
                "models": models,
            }

        return {
            "status": (
                "shadow_live_longitudinal_evidence_available"
                if evaluated_observation_count > 0
                else "shadow_live_longitudinal_evidence_pending"
            ),
            "asOf": cutoff.isoformat(),
            "symbol": normalized_symbol,
            "requestedHorizons": list(requested_horizons),
            "persistedCandidateCount": candidate_count,
            "eligibleCandidateCount": eligible_candidate_count,
            "evaluatedCandidateCount": evaluated_candidate_count,
            "skippedFutureCandidateCount": skipped_future_candidate_count,
            "evaluatedObservationCount": evaluated_observation_count,
            "horizons": horizon_payloads,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "action": None,
            "policy": {
                "lookAhead": "only_candidate_and_outcome_evidence_available_at_as_of",
                "modelVersionPooling": "forbidden_metrics_partitioned_by_frozen_model_fingerprint",
                "target": "realized_excess_return_vs_frozen_snapshot_benchmark",
                "measurement": "descriptive_forward_shadow_performance_only",
                "actionThresholds": "not_fit_from_this_service",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _metrics(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        if not observations:
            raise ValueError("No se pueden calcular métricas sin observaciones.")
        expected = [float(item["expectedExcessReturn"]) for item in observations]
        realized = [float(item["realizedExcessReturn"]) for item in observations]
        errors = [left - right for left, right in zip(expected, realized, strict=True)]
        count = len(errors)
        mse = sum(error * error for error in errors) / count
        mae = sum(abs(error) for error in errors) / count
        bias = sum(errors) / count
        baseline_mse = sum(value * value for value in realized) / count
        improvement = None
        if baseline_mse > 0.0:
            improvement = 1.0 - (mse / baseline_mse)
        sign_accuracy = sum(
            1 for left, right in zip(expected, realized, strict=True) if (left >= 0.0) == (right >= 0.0)
        ) / count
        correlation = self._correlation(expected, realized)
        return {
            "mse": mse,
            "rmse": math.sqrt(mse),
            "mae": mae,
            "bias": bias,
            "signAccuracy": sign_accuracy,
            "meanExpectedExcessReturn": sum(expected) / count,
            "meanRealizedExcessReturn": sum(realized) / count,
            "zeroExcessBaselineMse": baseline_mse,
            "mseImprovementVsZeroBaseline": improvement,
            "pearsonCorrelation": correlation,
        }

    def _correlation(self, left: list[float], right: list[float]) -> float | None:
        if len(left) < 2 or len(left) != len(right):
            return None
        left_mean = sum(left) / len(left)
        right_mean = sum(right) / len(right)
        numerator = sum(
            (x - left_mean) * (y - right_mean)
            for x, y in zip(left, right, strict=True)
        )
        left_ss = sum((x - left_mean) ** 2 for x in left)
        right_ss = sum((y - right_mean) ** 2 for y in right)
        denominator = math.sqrt(left_ss * right_ss)
        if denominator <= 0.0:
            return None
        result = numerator / denominator
        if not math.isfinite(result):
            raise ValueError("La correlación longitudinal no es finita.")
        return max(-1.0, min(1.0, result))

    def _assert_candidate_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato longitudinal debe mantener no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El candidato longitudinal debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato longitudinal no puede habilitar recomendaciones.")

    def _assert_evaluation_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La evaluación longitudinal debe mantener no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La evaluación longitudinal debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La evaluación longitudinal no puede habilitar recomendaciones.")

    def _horizons(self, values: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        if not isinstance(values, (tuple, list)) or not values:
            raise ValueError("horizons debe contener al menos un horizonte.")
        parsed: list[int] = []
        for value in values:
            if isinstance(value, bool):
                raise ValueError("Los horizontes deben ser enteros positivos.")
            try:
                horizon = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Los horizontes deben ser enteros positivos.") from exc
            if horizon <= 0:
                raise ValueError("Los horizontes deben ser enteros positivos.")
            parsed.append(horizon)
        if len(set(parsed)) != len(parsed):
            raise ValueError("Los horizontes no pueden repetirse.")
        return tuple(parsed)

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if parsed <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return parsed

    def _required_text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _required_sha256(self, value: object, field: str) -> str:
        result = self._required_text(value, field).lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result

    def _required_finite(self, value: object, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

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
