from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.repositories.longitudinal_oos_policy_repository import (
    LongitudinalOosPolicyRepository,
)
from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)
from app.services.recommendation_research_forecast_error_oos_service import (
    RecommendationResearchForecastErrorOosService,
)


class GovernedForecastErrorOosService:
    """Compose OOS measurement with durable human-governed sufficiency policy.

    Measurement remains descriptive and policy-independent. The policy repository
    is read point-in-time at the same ``as_of`` cutoff; no policy is created,
    approved, promoted, or mutated by this service.
    """

    def __init__(
        self,
        *,
        measurement_service: RecommendationResearchForecastErrorOosService | None = None,
        policy_service: LongitudinalOosSufficiencyPolicyService | None = None,
        policy_repository: LongitudinalOosPolicyRepository | None = None,
    ) -> None:
        self._measurement = measurement_service or RecommendationResearchForecastErrorOosService()
        self._policy = policy_service or LongitudinalOosSufficiencyPolicyService()
        self._repository = policy_repository or LongitudinalOosPolicyRepository()

    def evaluate(
        self,
        *,
        as_of: datetime,
        cohort_record: dict[str, Any] | None,
        error_records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        measurement = self._measurement.evaluate(
            as_of=as_of,
            cohort_record=cohort_record,
            error_records=error_records,
        )
        self._validate_measurement_contract(measurement)
        policy_record = self._repository.get_latest_policy(as_of=as_of)
        approval_record = None
        if policy_record is not None:
            artifact = policy_record.get("artifact")
            if not isinstance(artifact, dict):
                raise RuntimeError("La política longitudinal persistida perdió artifact.")
            fingerprint = artifact.get("policyFingerprint")
            if not isinstance(fingerprint, str):
                raise RuntimeError("La política longitudinal persistida perdió policyFingerprint.")
            approval_record = self._repository.get_latest_approval(
                policy_fingerprint=fingerprint,
                as_of=as_of,
            )

        sufficiency = self._policy.evaluate(
            as_of=as_of,
            measurement=measurement,
            policy_record=policy_record,
            approval_record=approval_record,
        )
        result = dict(measurement)
        result["longitudinalSufficiency"] = sufficiency
        result["productionLearningEligible"] = False
        result["productionEligible"] = False
        result["recommendationCandidateReady"] = False
        result["isWeightingReady"] = False
        policy = result.get("policy")
        if isinstance(policy, dict):
            policy = dict(policy)
            policy["longitudinalSufficiency"] = "durable_precommitted_human_approved_policy_required"
            policy["automaticProductionPromotion"] = False
            policy["automaticModelMutation"] = False
            policy["automaticTrading"] = False
            result["policy"] = policy
        return result

    def bind_external_challenger(
        self,
        *,
        provider: str,
        model_name: str,
        model_version: str,
        model_config: dict[str, Any],
        forecast_origin: datetime,
        input_observed_through: datetime,
        input_retrieved_at: datetime,
        horizon_seconds: int,
        forecast_value: float,
        baseline_name: str,
        baseline_value: float,
        source_provenance: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Bind an external model to research-only PIT/OOS governance."""
        origin = self._aware(forecast_origin, "forecast_origin")
        observed = self._aware(input_observed_through, "input_observed_through")
        retrieved = self._aware(input_retrieved_at, "input_retrieved_at")
        if observed > retrieved or retrieved > origin:
            raise ValueError(
                "External challenger PIT ordering must satisfy observed <= retrieved <= origin."
            )
        if isinstance(horizon_seconds, bool) or not isinstance(horizon_seconds, int) or horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be a positive integer.")
        forecast = self._finite(forecast_value, "forecast_value")
        baseline = self._finite(baseline_value, "baseline_value")
        if not isinstance(model_config, dict) or not model_config:
            raise ValueError("model_config must be a non-empty mapping.")
        if not isinstance(source_provenance, list) or not source_provenance:
            raise ValueError("source_provenance must preserve at least one source.")
        provenance: list[dict[str, str]] = []
        for item in source_provenance:
            if not isinstance(item, dict):
                raise ValueError("source_provenance contains an invalid entry.")
            source = self._text(item.get("source"), "source_provenance.source")
            source_observed = self._iso(item.get("observedAt"), "source_provenance.observedAt")
            source_retrieved = self._iso(item.get("retrievedAt"), "source_provenance.retrievedAt")
            if source_observed > source_retrieved or source_retrieved > origin:
                raise ValueError("External challenger provenance violates the PIT cutoff.")
            provenance.append({
                "source": source,
                "observedAt": source_observed.isoformat(),
                "retrievedAt": source_retrieved.isoformat(),
            })
        return {
            "module": "external_forecast_challenger_contract",
            "provider": self._text(provider, "provider"),
            "modelName": self._text(model_name, "model_name"),
            "modelVersion": self._text(model_version, "model_version"),
            "modelConfig": dict(model_config),
            "forecastOrigin": origin.isoformat(),
            "inputObservedThrough": observed.isoformat(),
            "inputRetrievedAt": retrieved.isoformat(),
            "horizonSeconds": horizon_seconds,
            "forecastValue": forecast,
            "baselineName": self._text(baseline_name, "baseline_name"),
            "baselineValue": baseline,
            "sourceProvenance": provenance,
            "evaluationMode": "prospective_oos_paired_with_baseline",
            "challengerOnly": True,
            "productionLearningEligible": False,
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "isWeightingReady": False,
            "automaticModelPromotion": False,
            "automaticWeighting": False,
            "automaticTrading": False,
            "policy": {
                "authority": "research_diagnostic_only",
                "longitudinalEvidence": "existing_human_governed_oos_gates_required",
                "baseline": "paired_baseline_required",
            },
        }

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone.")
        return value.astimezone(timezone.utc)

    def _iso(self, value: Any, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be ISO-8601.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO-8601.") from exc
        return self._aware(parsed, field)

    @staticmethod
    def _finite(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be finite.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{field} must be finite.")
        return number

    @staticmethod
    def _text(value: Any, field: str) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            raise ValueError(f"{field} is required.")
        return text

    @classmethod
    def _validate_measurement_contract(cls, measurement: dict[str, Any]) -> None:
        if not isinstance(measurement, dict):
            raise RuntimeError("La medición OOS gobernada no es estructurada.")
        span = measurement.get("evaluationSpanDays")
        if isinstance(span, bool) or not isinstance(span, (int, float)) or not math.isfinite(float(span)) or float(span) < 0:
            raise RuntimeError("La medición OOS contiene evaluationSpanDays inválido.")
        counts: dict[str, int] = {}
        for field in (
            "distinctEvaluationPeriodCount",
            "eligibleOutcomeCount",
            "forecastErrorCount",
            "distinctResolvedIssuerCount",
        ):
            counts[field] = cls._require_nonnegative_int(measurement.get(field), field)
        if counts["forecastErrorCount"] > counts["eligibleOutcomeCount"]:
            raise RuntimeError("La medición OOS contiene más forecast errors que outcomes elegibles.")
        horizons = measurement.get("horizons")
        if not isinstance(horizons, dict):
            raise RuntimeError("La medición OOS gobernada carece de horizons estructurados.")
        horizon_error_total = 0
        for horizon, payload in horizons.items():
            if not isinstance(horizon, str) or not horizon.strip() or not isinstance(payload, dict):
                raise RuntimeError("La medición OOS contiene un horizonte inválido.")
            horizon_error_total += cls._require_nonnegative_int(
                payload.get("forecastErrorCount"),
                f"horizons.{horizon}.forecastErrorCount",
            )
        if horizon_error_total != counts["forecastErrorCount"]:
            raise RuntimeError("La medición OOS no reconcilia forecastErrorCount con sus horizontes.")

    @staticmethod
    def _require_nonnegative_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"La medición OOS contiene {field} inválido.")
        return value
