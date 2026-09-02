from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)
from app.services.recommendation_shadow_live_cycle_attestation_service import (
    RecommendationShadowLiveCycleAttestationService,
)
from app.services.recommendation_shadow_live_decision_research_service import (
    RecommendationShadowLiveDecisionResearchService,
)


class _CandidateRepository(Protocol):
    def list_all(self) -> list[dict[str, Any]]: ...


class _DecisionResearchService(Protocol):
    def build(self, *, candidate_id: int) -> dict[str, Any]: ...


class _EvaluationService(Protocol):
    def evaluate(self, *, candidate_id: int, as_of: datetime) -> dict[str, Any]: ...


class _AttestationService(Protocol):
    def get_for_candidate(self, *, candidate_id: int) -> dict[str, Any] | None: ...


class RecommendationShadowActionCalibrationDatasetService:
    """Build a provenance-gated forward-live dataset for future action calibration.

    Only candidates carrying the immutable trusted persisted-live-cycle attestation
    may contribute rows. Labels are admitted only after their PIT outcomes matured
    by ``as_of``. The service deliberately does not fit action thresholds, scores,
    conviction or BUY/HOLD/REDUCE/SELL.
    """

    DATASET_VERSION = "shadow-action-calibration-v2"
    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        decision_research_service: _DecisionResearchService | None = None,
        evaluation_service: _EvaluationService | None = None,
        attestation_service: _AttestationService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._decision_research_service = (
            decision_research_service or RecommendationShadowLiveDecisionResearchService()
        )
        self._evaluation_service = (
            evaluation_service or RecommendationShadowLiveCandidateEvaluationService()
        )
        self._attestation_service = (
            attestation_service or RecommendationShadowLiveCycleAttestationService()
        )

    def build(
        self,
        *,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        requested_horizons = self._horizons(horizons)
        normalized_symbol = str(symbol or "").strip().upper() or None

        rows: list[dict[str, Any]] = []
        counters = {
            "persistedCandidateCount": 0,
            "unattestedCandidateCount": 0,
            "skippedFutureCandidateCount": 0,
            "skippedSymbolCount": 0,
            "pendingUncertaintyCandidateCount": 0,
            "pendingOutcomeRowCount": 0,
            "noPredictionRowCount": 0,
        }
        seen_candidate_fingerprints: set[str] = set()

        for stored in self._candidate_repository.list_all():
            candidate_id = self._positive_int(stored.get("id"), "candidate.id")
            counters["persistedCandidateCount"] += 1
            stored_fingerprint = self._sha256(
                stored.get("candidate_fingerprint"), "stored.candidate_fingerprint"
            )
            if stored_fingerprint in seen_candidate_fingerprints:
                raise ValueError("Existe un candidateFingerprint live duplicado.")
            seen_candidate_fingerprints.add(stored_fingerprint)

            attestation = self._attestation_service.get_for_candidate(
                candidate_id=candidate_id
            )
            if attestation is None:
                counters["unattestedCandidateCount"] += 1
                continue
            self._assert_attestation_shadow(attestation)
            if self._positive_int(attestation.get("candidateId"), "attestation.candidateId") != candidate_id:
                raise ValueError("La atestación live cambió candidateId.")
            if self._sha256(
                attestation.get("candidateFingerprint"),
                "attestation.candidateFingerprint",
            ) != stored_fingerprint:
                raise ValueError("La atestación live cambió candidateFingerprint.")

            decision = self._decision_research_service.build(candidate_id=candidate_id)
            self._assert_decision_shadow(decision)
            candidate_fingerprint = self._sha256(
                decision.get("candidateFingerprint"), "candidateFingerprint"
            )
            if candidate_fingerprint != stored_fingerprint:
                raise ValueError("Decision research no coincide con el candidato persistido.")
            decision_fingerprint = self._sha256(
                decision.get("decisionResearchFingerprint"),
                "decisionResearchFingerprint",
            )
            uncertainty_fingerprint = self._sha256(
                decision.get("uncertaintyFingerprint"), "uncertaintyFingerprint"
            )
            if self._sha256(
                attestation.get("decisionResearchFingerprint"),
                "attestation.decisionResearchFingerprint",
            ) != decision_fingerprint:
                raise ValueError("La atestación no coincide con decision research.")
            if self._sha256(
                attestation.get("uncertaintyFingerprint"),
                "attestation.uncertaintyFingerprint",
            ) != uncertainty_fingerprint:
                raise ValueError("La atestación no coincide con la incertidumbre ex-ante.")

            candidate_symbol = self._required_text(
                decision.get("symbol"), "decision.symbol"
            ).upper()
            candidate_as_of = self._parse_aware(decision.get("asOf"), "decision.asOf")
            if self._required_text(attestation.get("symbol"), "attestation.symbol").upper() != candidate_symbol:
                raise ValueError("La atestación cambió el símbolo del candidato live.")
            if self._parse_aware(attestation.get("asOf"), "attestation.asOf") != candidate_as_of:
                raise ValueError("La atestación cambió el asOf del candidato live.")
            if normalized_symbol is not None and candidate_symbol != normalized_symbol:
                counters["skippedSymbolCount"] += 1
                continue
            if candidate_as_of > cutoff:
                counters["skippedFutureCandidateCount"] += 1
                continue

            decision_horizons = decision.get("horizons")
            risk_context = decision.get("riskContext")
            if not isinstance(decision_horizons, dict):
                raise ValueError("Decision research carece de horizontes válidos.")
            if not isinstance(risk_context, dict):
                raise ValueError("Decision research carece de riskContext válido.")
            if decision.get("status") != "shadow_live_decision_research_ready":
                counters["pendingUncertaintyCandidateCount"] += 1

            evaluation = self._evaluation_service.evaluate(
                candidate_id=candidate_id,
                as_of=cutoff,
            )
            self._assert_evaluation_shadow(evaluation)
            if self._sha256(
                evaluation.get("candidateFingerprint"),
                "evaluation.candidateFingerprint",
            ) != candidate_fingerprint:
                raise ValueError("La evaluación cambió el candidato de decision research.")
            if self._required_text(evaluation.get("symbol"), "evaluation.symbol").upper() != candidate_symbol:
                raise ValueError("La evaluación cambió el símbolo de decision research.")
            if self._parse_aware(evaluation.get("candidateAsOf"), "evaluation.candidateAsOf") != candidate_as_of:
                raise ValueError("La evaluación cambió el asOf del candidato live.")
            evaluation_horizons = evaluation.get("horizons")
            if not isinstance(evaluation_horizons, dict):
                raise ValueError("La evaluación carece de horizontes válidos.")

            for horizon in requested_horizons:
                research = decision_horizons.get(str(horizon))
                outcome = evaluation_horizons.get(str(horizon))
                if research is None or outcome is None:
                    continue
                if not isinstance(research, dict) or not isinstance(outcome, dict):
                    raise ValueError("Un horizonte de calibración tiene formato inválido.")
                if self._positive_int(research.get("horizonDays"), "research.horizonDays") != horizon:
                    raise ValueError("El horizonte de decision research es inconsistente.")
                if self._positive_int(outcome.get("horizonDays"), "outcome.horizonDays") != horizon:
                    raise ValueError("El horizonte del outcome es inconsistente.")
                if research.get("status") == "not_applicable_no_live_prediction":
                    counters["noPredictionRowCount"] += 1
                    continue
                if research.get("status") != "decision_research_evidence_ready":
                    continue
                if outcome.get("status") != "evaluated":
                    counters["pendingOutcomeRowCount"] += 1
                    continue

                uncertainty = research.get("uncertainty")
                scenarios = research.get("scenarios")
                direction = research.get("directionDiagnostics")
                if not isinstance(uncertainty, dict) or not isinstance(scenarios, dict):
                    raise ValueError("Decision research listo carece de incertidumbre o escenarios.")
                if not isinstance(direction, dict):
                    raise ValueError("Decision research listo carece de diagnósticos direccionales.")
                due_at = self._parse_aware(outcome.get("outcomeDueAt"), "outcomeDueAt")
                evaluated_at = self._parse_aware(
                    outcome.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
                )
                if evaluated_at < due_at:
                    raise ValueError("Un outcome fue evaluado antes de su vencimiento.")
                if evaluated_at > cutoff:
                    raise ValueError("Un outcome futuro atravesó el corte de calibración.")

                row = {
                    "candidateId": candidate_id,
                    "candidateFingerprint": candidate_fingerprint,
                    "liveCycleAttestationFingerprint": self._sha256(
                        attestation.get("attestationFingerprint"),
                        "attestationFingerprint",
                    ),
                    "decisionResearchFingerprint": decision_fingerprint,
                    "uncertaintyFingerprint": uncertainty_fingerprint,
                    "symbol": candidate_symbol,
                    "candidateAsOf": candidate_as_of.isoformat(),
                    "horizonDays": horizon,
                    "expectedExcessReturn": self._finite(research.get("expectedExcessReturn"), "expectedExcessReturn"),
                    "researchStrength": self._finite(research.get("researchStrength"), "researchStrength"),
                    "conservativeResearchStrength": self._finite(research.get("conservativeResearchStrength"), "conservativeResearchStrength"),
                    "riskAdjustedResearchStrength": self._optional_finite(research.get("riskAdjustedResearchStrength"), "riskAdjustedResearchStrength"),
                    "residualRmse": self._positive_finite(uncertainty.get("rmse"), "uncertainty.rmse"),
                    "residualMae": self._positive_finite(uncertainty.get("mae"), "uncertainty.mae"),
                    "uncertaintyObservationCount": self._positive_int(uncertainty.get("observationCount"), "uncertainty.observationCount"),
                    "lowerEmpiricalExcessReturn": self._finite(scenarios.get("lowerEmpiricalExcessReturn"), "lowerEmpiricalExcessReturn"),
                    "medianEmpiricalExcessReturn": self._finite(scenarios.get("medianEmpiricalExcessReturn"), "medianEmpiricalExcessReturn"),
                    "upperEmpiricalExcessReturn": self._finite(scenarios.get("upperEmpiricalExcessReturn"), "upperEmpiricalExcessReturn"),
                    "pointEstimatePositive": self._boolean(direction.get("pointEstimatePositive"), "pointEstimatePositive"),
                    "medianScenarioPositive": self._boolean(direction.get("medianScenarioPositive"), "medianScenarioPositive"),
                    "lowerScenarioPositive": self._boolean(direction.get("lowerScenarioPositive"), "lowerScenarioPositive"),
                    "upperScenarioNegative": self._boolean(direction.get("upperScenarioNegative"), "upperScenarioNegative"),
                    "riskScore": self._optional_finite(risk_context.get("riskScore"), "riskScore"),
                    "annualizedVolatility": self._optional_finite(risk_context.get("annualizedVolatility"), "annualizedVolatility"),
                    "maxDrawdown60d": self._optional_finite(risk_context.get("maxDrawdown60d"), "maxDrawdown60d"),
                    "realizedExcessReturn": self._finite(outcome.get("realizedExcessReturn"), "realizedExcessReturn"),
                    "realizedReturn": self._optional_finite(outcome.get("realizedReturn"), "realizedReturn"),
                    "benchmarkReturn": self._optional_finite(outcome.get("benchmarkReturn"), "benchmarkReturn"),
                    "predictionError": self._finite(outcome.get("predictionError"), "predictionError"),
                    "directionCorrect": self._boolean(outcome.get("directionCorrect"), "directionCorrect"),
                    "outcomeDueAt": due_at.isoformat(),
                    "outcomeEvaluatedAt": evaluated_at.isoformat(),
                }
                self._assert_scenario_order(row)
                rows.append(row)

        rows.sort(
            key=lambda row: (
                row["candidateAsOf"], row["symbol"], row["candidateId"], row["horizonDays"]
            )
        )
        core = {
            "datasetVersion": self.DATASET_VERSION,
            "asOf": cutoff.isoformat(),
            "symbol": normalized_symbol,
            "requestedHorizons": list(requested_horizons),
            "rowCount": len(rows),
            "rows": rows,
        }
        return {
            "status": "shadow_action_calibration_dataset_available" if rows else "shadow_action_calibration_dataset_pending",
            **core,
            "datasetFingerprint": self._fingerprint(core),
            **counters,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "evidenceSource": "trusted_persisted_live_cycle_attestation_v1_only",
                "legacyUnattestedCandidates": "excluded_not_assumed_trusted",
                "decisionInputs": "persisted_candidate_plus_sealed_ex_ante_uncertainty",
                "labels": "matured_pit_outcomes_available_by_as_of",
                "researchHoldoutReuse": False,
                "actionThresholds": "not_fit",
                "score": "not_calibrated",
                "conviction": "not_calibrated",
                "nextStage": "chronological_threshold_research_with_new_validation_reserve",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _assert_attestation_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("status") != "shadow_live_cycle_attestation_available":
            raise ValueError("La atestación live no está disponible.")
        if payload.get("advisoryStatus") != "no_advice" or payload.get("productionEligible") is not False:
            raise ValueError("La atestación live violó el contrato shadow.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La atestación live no puede habilitar recomendaciones.")
        if payload.get("frozenCandidateSource") != "sqlite_persisted_and_revalidated":
            raise ValueError("La atestación live carece de provenance persistida.")
        if payload.get("callerSuppliedFrozenBundleJsonTrusted") is not False:
            raise ValueError("La atestación live no puede confiar en JSON del caller.")
        if payload.get("frozenBundleIntegrity") != "gated_freeze_revalidated_after_load":
            raise ValueError("La atestación live carece de revalidación gated-freeze.")

    def _assert_decision_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice" or payload.get("productionEligible") is not False:
            raise ValueError("Decision research violó el contrato shadow.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("Decision research no puede habilitar recomendaciones.")
        if payload.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("Decision research no puede promover calibración automáticamente.")
        if payload.get("action") is not None or payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError("Decision research no puede contener decisión calibrada.")

    def _assert_evaluation_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice" or payload.get("productionEligible") is not False:
            raise ValueError("La evaluación violó el contrato shadow.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La evaluación no puede habilitar recomendaciones.")

    def _assert_scenario_order(self, row: dict[str, Any]) -> None:
        if not (
            float(row["lowerEmpiricalExcessReturn"])
            <= float(row["medianEmpiricalExcessReturn"])
            <= float(row["upperEmpiricalExcessReturn"])
        ):
            raise ValueError("Los escenarios del dataset no están ordenados.")

    def _horizons(self, values: tuple[int, ...] | list[int]) -> tuple[int, ...]:
        if not isinstance(values, (tuple, list)) or not values:
            raise ValueError("horizons debe contener al menos un horizonte.")
        result = tuple(self._positive_int(value, "horizon") for value in values)
        if len(set(result)) != len(result):
            raise ValueError("Los horizontes no pueden repetirse.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _required_text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = self._required_text(value, field).lower()
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result

    def _finite(self, value: object, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _optional_finite(self, value: object, field: str) -> float | None:
        if value is None:
            return None
        return self._finite(value, field)

    def _boolean(self, value: object, field: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field} debe ser booleano.")
        return value

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
