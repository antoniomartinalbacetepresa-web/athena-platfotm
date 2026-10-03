from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
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
    def get(self, candidate_id: int) -> dict[str, Any] | None: ...

    def list_all(self) -> list[dict[str, Any]]: ...


class _CandidateService(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _EvaluationService(Protocol):
    def evaluate(self, *, candidate_id: int, as_of: datetime) -> dict[str, Any]: ...


class RecommendationShadowLiveUncertaintyService:
    """Build ex-ante empirical uncertainty from prior live-shadow residuals.

    The cutoff is the candidate's own ``asOf``. Later outcomes are therefore
    impossible to use when reconstructing the uncertainty that was available at
    inference time. Residuals must come from the exact same frozen-model
    fingerprint and symbol. A deterministic spacing rule keeps selected forecast
    windows at least one horizon apart to avoid treating heavily overlapping
    forward returns as independent evidence.
    """

    ARTIFACT_VERSION = "shadow-live-uncertainty-v1"

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        candidate_service: _CandidateService | None = None,
        evaluation_service: _EvaluationService | None = None,
        minimum_observations: int = 20,
    ) -> None:
        if isinstance(minimum_observations, bool) or minimum_observations < 2:
            raise ValueError("minimum_observations debe ser al menos 2.")
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()
        self._evaluation_service = (
            evaluation_service or RecommendationShadowLiveCandidateEvaluationService()
        )
        self._minimum_observations = int(minimum_observations)

    def evaluate(self, *, candidate_id: int) -> dict[str, Any]:
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        stored = self._candidate_repository.get(candidate_id)
        if stored is None:
            raise ValueError("El candidato shadow live no existe.")
        candidate = self._validated_stored_candidate(stored)
        cutoff = self._parse_aware(candidate.get("asOf"), "candidate.asOf")
        symbol = self._required_text(candidate.get("symbol"), "candidate.symbol").upper()
        candidate_fingerprint = self._required_sha256(
            candidate.get("candidateFingerprint"), "candidateFingerprint"
        )

        prior = self._prior_candidates(
            current_candidate_id=candidate_id,
            current_candidate_fingerprint=candidate_fingerprint,
            symbol=symbol,
            cutoff=cutoff,
        )
        candidate_horizons = candidate.get("horizons")
        if not isinstance(candidate_horizons, dict):
            raise ValueError("El candidato live carece de horizontes válidos.")

        horizon_payloads: dict[str, dict[str, Any]] = {}
        calibrated_count = 0
        for raw_key, inference in candidate_horizons.items():
            if not isinstance(inference, dict):
                raise ValueError("Un horizonte del candidato tiene formato inválido.")
            horizon = self._positive_int(inference.get("horizonDays"), "horizonDays")
            if str(horizon) != str(raw_key):
                raise ValueError("La identidad de horizonte del candidato es inconsistente.")
            expected = self._optional_finite(inference.get("expectedExcessReturn"))
            model_fingerprint = inference.get("modelFingerprint")
            if expected is None:
                horizon_payloads[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "not_applicable_no_live_prediction",
                    "modelFingerprint": model_fingerprint,
                    "observationCount": 0,
                    "scenarios": None,
                }
                continue
            model_fingerprint = self._required_sha256(
                model_fingerprint, "modelFingerprint"
            )
            observations = self._residual_observations(
                prior=prior,
                horizon=horizon,
                model_fingerprint=model_fingerprint,
                cutoff=cutoff,
            )
            selected = self._non_overlapping(observations, horizon)
            if len(selected) < self._minimum_observations:
                horizon_payloads[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "insufficient_prior_forward_residual_history",
                    "modelFingerprint": model_fingerprint,
                    "expectedExcessReturn": expected,
                    "availableObservationCount": len(observations),
                    "observationCount": len(selected),
                    "minimumObservationCount": self._minimum_observations,
                    "scenarios": None,
                }
                continue

            residuals = [item["residual"] for item in selected]
            p10 = self._quantile(residuals, 0.10)
            p50 = self._quantile(residuals, 0.50)
            p90 = self._quantile(residuals, 0.90)
            mse = sum(value * value for value in residuals) / len(residuals)
            mae = sum(abs(value) for value in residuals) / len(residuals)
            mean = sum(residuals) / len(residuals)
            calibrated_count += 1
            horizon_payloads[str(horizon)] = {
                "horizonDays": horizon,
                "status": "empirical_forward_uncertainty_available",
                "modelFingerprint": model_fingerprint,
                "expectedExcessReturn": expected,
                "availableObservationCount": len(observations),
                "observationCount": len(selected),
                "minimumObservationCount": self._minimum_observations,
                "residualMetrics": {
                    "mean": mean,
                    "mse": mse,
                    "rmse": math.sqrt(mse),
                    "mae": mae,
                    "p10": p10,
                    "p50": p50,
                    "p90": p90,
                },
                "scenarios": {
                    "lowerEmpiricalExcessReturn": expected + p10,
                    "medianEmpiricalExcessReturn": expected + p50,
                    "upperEmpiricalExcessReturn": expected + p90,
                    "p10ToP90Width": p90 - p10,
                },
                "firstEvidenceAsOf": selected[0]["candidateAsOf"].isoformat(),
                "lastEvidenceAsOf": selected[-1]["candidateAsOf"].isoformat(),
                "independenceStatus": "calendar_horizon_non_overlapping_forecast_origins",
            }

        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "status": (
                "shadow_live_empirical_uncertainty_available"
                if calibrated_count > 0
                else "shadow_live_empirical_uncertainty_pending"
            ),
            "candidateId": candidate_id,
            "candidateFingerprint": candidate_fingerprint,
            "symbol": symbol,
            "asOf": cutoff.isoformat(),
            "calibratedHorizonCount": calibrated_count,
            "horizons": horizon_payloads,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "action": None,
            "conviction": None,
            "policy": {
                "cutoff": "candidate_as_of_not_request_time",
                "lookAhead": "only_prior_candidates_and_outcomes_mature_by_candidate_as_of",
                "modelIdentity": "exact_frozen_model_sha256_fingerprint",
                "issuerIdentity": "same_normalized_symbol",
                "overlapControl": "forecast_origins_spaced_at_least_one_calendar_horizon",
                "scenarioMeaning": "empirical_residual_distribution_not_probability_guarantee",
                "minimumObservations": self._minimum_observations,
                "actionThresholds": "not_fit",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _prior_candidates(
        self,
        *,
        current_candidate_id: int,
        current_candidate_fingerprint: str,
        symbol: str,
        cutoff: datetime,
    ) -> list[tuple[int, dict[str, Any], datetime]]:
        result: list[tuple[int, dict[str, Any], datetime]] = []
        seen_fingerprints: set[str] = set()
        for stored in self._candidate_repository.list_all():
            stored_id = self._positive_int(stored.get("id"), "stored.id")
            candidate = self._validated_stored_candidate(stored)
            fingerprint = self._required_sha256(
                candidate.get("candidateFingerprint"), "candidateFingerprint"
            )
            if fingerprint in seen_fingerprints:
                raise ValueError("Existe un candidateFingerprint duplicado en persistencia.")
            seen_fingerprints.add(fingerprint)
            if stored_id == current_candidate_id or fingerprint == current_candidate_fingerprint:
                continue
            candidate_symbol = self._required_text(
                candidate.get("symbol"), "candidate.symbol"
            ).upper()
            if candidate_symbol != symbol:
                continue
            candidate_as_of = self._parse_aware(candidate.get("asOf"), "candidate.asOf")
            if candidate_as_of >= cutoff:
                continue
            result.append((stored_id, candidate, candidate_as_of))
        result.sort(key=lambda item: (item[2], item[0]))
        return result

    def _residual_observations(
        self,
        *,
        prior: list[tuple[int, dict[str, Any], datetime]],
        horizon: int,
        model_fingerprint: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for candidate_id, candidate, candidate_as_of in prior:
            horizons = candidate.get("horizons")
            if not isinstance(horizons, dict):
                raise ValueError("Un candidato previo carece de horizontes válidos.")
            inference = horizons.get(str(horizon))
            if not isinstance(inference, dict):
                continue
            if inference.get("expectedExcessReturn") is None:
                continue
            prior_model = self._required_sha256(
                inference.get("modelFingerprint"), "prior.modelFingerprint"
            )
            if prior_model != model_fingerprint:
                continue

            evaluation = self._evaluation_service.evaluate(
                candidate_id=candidate_id,
                as_of=cutoff,
            )
            self._assert_evaluation_shadow(evaluation)
            if self._required_sha256(
                evaluation.get("candidateFingerprint"),
                "evaluation.candidateFingerprint",
            ) != self._required_sha256(
                candidate.get("candidateFingerprint"), "candidateFingerprint"
            ):
                raise ValueError("La evaluación previa cambió el candidato de referencia.")
            evaluated_horizons = evaluation.get("horizons")
            if not isinstance(evaluated_horizons, dict):
                raise ValueError("La evaluación previa carece de horizontes válidos.")
            outcome = evaluated_horizons.get(str(horizon))
            if not isinstance(outcome, dict) or outcome.get("status") != "evaluated":
                continue
            expected = self._required_finite(
                outcome.get("expectedExcessReturn"), "expectedExcessReturn"
            )
            realized = self._required_finite(
                outcome.get("realizedExcessReturn"), "realizedExcessReturn"
            )
            observations.append(
                {
                    "candidateId": candidate_id,
                    "candidateAsOf": candidate_as_of,
                    "residual": realized - expected,
                }
            )
        return observations

    def _non_overlapping(
        self,
        observations: list[dict[str, Any]],
        horizon: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        next_allowed: datetime | None = None
        spacing = timedelta(days=horizon)
        for item in observations:
            candidate_as_of = item["candidateAsOf"]
            if not isinstance(candidate_as_of, datetime):
                raise ValueError("candidateAsOf interno inválido.")
            if next_allowed is not None and candidate_as_of < next_allowed:
                continue
            selected.append(item)
            next_allowed = candidate_as_of + spacing
        return selected

    def _validated_stored_candidate(self, stored: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(stored, dict):
            raise ValueError("Persistencia live devolvió una fila inválida.")
        artifact = stored.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Un candidato live persistido carece de artefacto válido.")
        candidate = self._candidate_service.validate_artifact(artifact)
        self._assert_candidate_shadow(candidate)
        stored_fingerprint = self._required_sha256(
            stored.get("candidate_fingerprint"), "stored.candidate_fingerprint"
        )
        artifact_fingerprint = self._required_sha256(
            candidate.get("candidateFingerprint"), "candidateFingerprint"
        )
        if stored_fingerprint != artifact_fingerprint:
            raise ValueError("El fingerprint persistido no coincide con el candidato live.")
        return candidate

    def _assert_candidate_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El candidato debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato no puede habilitar recomendaciones.")

    def _assert_evaluation_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La evaluación previa debe mantener no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La evaluación previa debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La evaluación previa no puede habilitar recomendaciones.")

    def _quantile(self, values: list[float], probability: float) -> float:
        if not values:
            raise ValueError("No se puede calcular un cuantil sin datos.")
        ordered = sorted(values)
        position = (len(ordered) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

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

    def _optional_finite(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _required_finite(self, value: object, field: str) -> float:
        result = self._optional_finite(value)
        if result is None:
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
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)
