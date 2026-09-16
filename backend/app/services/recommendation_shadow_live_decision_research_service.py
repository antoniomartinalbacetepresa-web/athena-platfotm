from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol

from app.services.recommendation_shadow_live_audit_service import (
    RecommendationShadowLiveAuditService,
)


class _AuditService(Protocol):
    def get(self, *, candidate_id: int) -> dict[str, Any]: ...


class RecommendationShadowLiveDecisionResearchService:
    """Build an immutable, no-advice decision-research view from sealed live evidence.

    This layer does not fit action thresholds and does not emit BUY/HOLD/REDUCE/SELL.
    It only combines the already persisted point estimate, empirical ex-ante
    uncertainty and risk context into transparent diagnostics that can later be
    calibrated against realized outcomes using genuinely new evidence.
    """

    ARTIFACT_VERSION = "shadow-live-decision-research-v1"

    def __init__(self, *, audit_service: _AuditService | None = None) -> None:
        self._audit_service = audit_service or RecommendationShadowLiveAuditService()

    def build(self, *, candidate_id: int) -> dict[str, Any]:
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        audit = self._audit_service.get(candidate_id=candidate_id)
        self._assert_audit_shadow(audit)

        candidate = audit.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("La auditoría carece de candidato válido.")
        uncertainty = audit.get("uncertainty")
        if uncertainty is not None and not isinstance(uncertainty, dict):
            raise ValueError("La incertidumbre auditada tiene formato inválido.")

        candidate_fingerprint = self._sha256(
            audit.get("candidateFingerprint"), "candidateFingerprint"
        )
        uncertainty_fingerprint = audit.get("uncertaintyFingerprint")
        if uncertainty_fingerprint is not None:
            uncertainty_fingerprint = self._sha256(
                uncertainty_fingerprint, "uncertaintyFingerprint"
            )

        risk_context = candidate.get("riskContext")
        if not isinstance(risk_context, dict):
            raise ValueError("El candidato auditado carece de riskContext.")
        risk_score = self._optional_finite(risk_context.get("riskScore"))
        annualized_volatility = self._optional_finite(
            risk_context.get("annualizedVolatility")
        )
        drawdown = self._optional_finite(risk_context.get("maxDrawdown60d"))

        candidate_horizons = candidate.get("horizons")
        if not isinstance(candidate_horizons, dict):
            raise ValueError("El candidato auditado carece de horizontes válidos.")
        uncertainty_horizons = (
            uncertainty.get("horizons") if isinstance(uncertainty, dict) else {}
        )
        if not isinstance(uncertainty_horizons, dict):
            raise ValueError("La incertidumbre auditada carece de horizontes válidos.")

        horizons: dict[str, dict[str, Any]] = {}
        research_ready = 0
        for key, inference in candidate_horizons.items():
            if not isinstance(inference, dict):
                raise ValueError("Un horizonte del candidato tiene formato inválido.")
            horizon = self._positive_int(inference.get("horizonDays"), "horizonDays")
            if str(horizon) != str(key):
                raise ValueError("La identidad del horizonte del candidato es inconsistente.")
            expected = self._optional_finite(inference.get("expectedExcessReturn"))
            if expected is None:
                horizons[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "not_applicable_no_live_prediction",
                    "expectedExcessReturn": None,
                    "researchStrength": None,
                    "scenarios": None,
                }
                continue

            u = uncertainty_horizons.get(str(horizon))
            if not isinstance(u, dict) or u.get("status") != "empirical_forward_uncertainty_available":
                horizons[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "pending_empirical_uncertainty",
                    "expectedExcessReturn": expected,
                    "researchStrength": None,
                    "scenarios": None,
                }
                continue

            metrics = u.get("residualMetrics")
            scenarios = u.get("scenarios")
            if not isinstance(metrics, dict) or not isinstance(scenarios, dict):
                raise ValueError("La incertidumbre calibrada carece de métricas o escenarios.")
            rmse = self._positive_finite(metrics.get("rmse"), "residualMetrics.rmse")
            mae = self._positive_finite(metrics.get("mae"), "residualMetrics.mae")
            lower = self._required_finite(
                scenarios.get("lowerEmpiricalExcessReturn"),
                "lowerEmpiricalExcessReturn",
            )
            median = self._required_finite(
                scenarios.get("medianEmpiricalExcessReturn"),
                "medianEmpiricalExcessReturn",
            )
            upper = self._required_finite(
                scenarios.get("upperEmpiricalExcessReturn"),
                "upperEmpiricalExcessReturn",
            )
            if not lower <= median <= upper:
                raise ValueError("Los escenarios empíricos no están ordenados.")

            strength = expected / rmse
            conservative_strength = lower / rmse
            risk_adjusted_strength = self._risk_adjusted_strength(
                strength=strength,
                risk_score=risk_score,
            )
            research_ready += 1
            horizons[str(horizon)] = {
                "horizonDays": horizon,
                "status": "decision_research_evidence_ready",
                "expectedExcessReturn": expected,
                "researchStrength": strength,
                "conservativeResearchStrength": conservative_strength,
                "riskAdjustedResearchStrength": risk_adjusted_strength,
                "uncertainty": {
                    "rmse": rmse,
                    "mae": mae,
                    "observationCount": self._positive_int(
                        u.get("observationCount"), "observationCount"
                    ),
                },
                "scenarios": {
                    "lowerEmpiricalExcessReturn": lower,
                    "medianEmpiricalExcessReturn": median,
                    "upperEmpiricalExcessReturn": upper,
                },
                "directionDiagnostics": {
                    "pointEstimatePositive": expected > 0.0,
                    "medianScenarioPositive": median > 0.0,
                    "lowerScenarioPositive": lower > 0.0,
                    "upperScenarioNegative": upper < 0.0,
                },
            }

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "candidateId": candidate_id,
            "candidateFingerprint": candidate_fingerprint,
            "uncertaintyFingerprint": uncertainty_fingerprint,
            "symbol": candidate.get("symbol"),
            "asOf": candidate.get("asOf"),
            "researchReadyHorizonCount": research_ready,
            "horizons": horizons,
            "riskContext": {
                "riskScore": risk_score,
                "annualizedVolatility": annualized_volatility,
                "maxDrawdown60d": drawdown,
            },
        }
        return {
            "status": (
                "shadow_live_decision_research_ready"
                if research_ready > 0
                else "shadow_live_decision_research_pending"
            ),
            **core,
            "decisionResearchFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "source": "persisted_immutable_live_candidate_and_ex_ante_uncertainty",
                "researchStrength": "expected_excess_return_divided_by_empirical_residual_rmse",
                "riskAdjustment": "diagnostic_only_not_calibrated_action_logic",
                "scenarioMeaning": "empirical_residual_scenarios_not_probability_guarantees",
                "actionThresholds": "not_fit",
                "score": "not_calibrated",
                "conviction": "not_calibrated",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de decision research no compatible.")
        self._assert_shadow_payload(artifact, "decision_research")
        fingerprint = self._sha256(
            artifact.get("decisionResearchFingerprint"),
            "decisionResearchFingerprint",
        )
        core_keys = (
            "artifactVersion",
            "candidateId",
            "candidateFingerprint",
            "uncertaintyFingerprint",
            "symbol",
            "asOf",
            "researchReadyHorizonCount",
            "horizons",
            "riskContext",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("El artefacto decision research fue modificado tras su creación.")
        return artifact

    def _assert_audit_shadow(self, audit: dict[str, Any]) -> None:
        if not isinstance(audit, dict):
            raise ValueError("La auditoría devolvió un contrato inválido.")
        self._assert_shadow_payload(audit, "audit")
        if audit.get("status") != "shadow_live_audit_available":
            raise ValueError("La evidencia live no está disponible para investigación de decisión.")

    def _assert_shadow_payload(self, payload: dict[str, Any], field: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{field} debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{field} debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{field} no puede habilitar recomendaciones.")
        if payload.get("action") is not None:
            raise ValueError(f"{field} no puede contener action.")

    def _risk_adjusted_strength(self, *, strength: float, risk_score: float | None) -> float | None:
        if risk_score is None:
            return None
        if risk_score < 0.0 or risk_score > 1.0:
            raise ValueError("riskScore debe estar entre 0 y 1 para el diagnóstico.")
        result = strength * (1.0 - risk_score)
        if not math.isfinite(result):
            raise ValueError("El diagnóstico ajustado por riesgo no es finito.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._required_finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result
