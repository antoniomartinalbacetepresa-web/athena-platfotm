from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
from typing import Any


class RecommendationResearchForecastErrorOosService:
    """Aggregate verified forecast errors over one verified issuer-aware OOS cohort.

    This is a descriptive measurement layer only. It never selects thresholds,
    claims statistical independence, estimates skill, changes a model, or turns
    forecast error into an investment recommendation.
    """

    def evaluate(
        self,
        *,
        as_of: datetime,
        cohort_record: dict[str, Any] | None,
        error_records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        if cohort_record is None:
            if error_records:
                raise ValueError("No puede haber forecast errors OOS sin una cohorte PIT elegible.")
            return self._pending()

        artifact = cohort_record.get("artifact") if isinstance(cohort_record, dict) else None
        if not isinstance(artifact, dict):
            raise ValueError("La cohorte OOS persistida carece de artifact válido.")
        self._assert_cohort_safe(artifact)
        cohort_as_of = self._aware_iso(artifact.get("asOf"), "cohort.asOf")
        if cohort_as_of > cutoff:
            raise ValueError("La cohorte OOS es posterior al as_of del diagnóstico.")

        rows = artifact.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("La cohorte OOS carece de filas observacionales.")
        by_outcome: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("La cohorte OOS contiene una fila inválida.")
            outcome_hash = self._sha_text(row.get("outcomeHash"), "cohort.outcomeHash")
            if outcome_hash in by_outcome:
                raise ValueError("La cohorte OOS repite outcomeHash.")
            by_outcome[outcome_hash] = row

        normalized_errors: list[dict[str, Any]] = []
        seen_error_hashes: set[str] = set()
        seen_outcomes: set[str] = set()
        for record in error_records:
            normalized = self._normalize_error(record, cutoff=cutoff)
            error_hash = str(normalized["errorHash"])
            outcome_hash = str(normalized["outcomeHash"])
            if error_hash in seen_error_hashes:
                raise ValueError("Forecast error OOS repite errorHash.")
            if outcome_hash in seen_outcomes:
                raise ValueError("Forecast error OOS repite outcomeHash.")
            seen_error_hashes.add(error_hash)
            seen_outcomes.add(outcome_hash)
            row = by_outcome.get(outcome_hash)
            if row is None:
                raise ValueError("Forecast error referencia un outcome fuera de la cohorte OOS.")
            self._assert_error_matches_cohort_row(normalized, row)
            identity = row.get("issuerIdentity")
            if not isinstance(identity, dict):
                raise ValueError("La fila OOS perdió issuerIdentity.")
            normalized["issuerIdentity"] = identity
            normalized_errors.append(normalized)

        normalized_errors.sort(
            key=lambda item: (
                int(item["horizonSeconds"]),
                str(item["periodEnd"]),
                str(item["outcomeHash"]),
            )
        )

        horizons: dict[str, dict[str, Any]] = {}
        horizon_rows: dict[int, list[dict[str, Any]]] = {}
        for item in normalized_errors:
            horizon_rows.setdefault(int(item["horizonSeconds"]), []).append(item)

        cohort_horizons = artifact.get("horizons")
        if not isinstance(cohort_horizons, dict):
            raise ValueError("La cohorte OOS perdió horizons.")
        for horizon_key, cohort_horizon in sorted(
            cohort_horizons.items(), key=lambda pair: int(pair[0])
        ):
            if not isinstance(cohort_horizon, dict):
                raise ValueError("La cohorte OOS contiene un horizonte inválido.")
            horizon_seconds = int(horizon_key)
            errors = horizon_rows.get(horizon_seconds, [])
            resolved = [
                str(item["issuerIdentity"].get("issuerId"))
                for item in errors
                if item["issuerIdentity"].get("issuerId") is not None
            ]
            issuer_counts = Counter(resolved)
            eligible = self._nonnegative_int(
                cohort_horizon.get("observationCount"),
                f"cohort.horizons.{horizon_key}.observationCount",
            )
            if len(errors) > eligible:
                raise ValueError("Hay más forecast errors que outcomes elegibles en un horizonte.")
            horizons[str(horizon_seconds)] = {
                "horizonSeconds": horizon_seconds,
                "horizonDays": cohort_horizon.get("horizonDays"),
                "eligibleOutcomeCount": eligible,
                "forecastErrorCount": len(errors),
                "missingForecastErrorCount": eligible - len(errors),
                "measurementCoverage": (len(errors) / eligible) if eligible else 0.0,
                "resolvedIssuerErrorCount": len(resolved),
                "unresolvedIssuerErrorCount": len(errors) - len(resolved),
                "distinctResolvedIssuerCount": len(issuer_counts),
                "maximumErrorsPerResolvedIssuer": max(issuer_counts.values(), default=0),
                "issuerErrorCounts": dict(sorted(issuer_counts.items())),
                **self._longitudinal_summary(errors),
                "metrics": self._metrics(errors),
                "errorHashes": [str(item["errorHash"]) for item in errors],
            }

        all_resolved = [
            str(item["issuerIdentity"].get("issuerId"))
            for item in normalized_errors
            if item["issuerIdentity"].get("issuerId") is not None
        ]
        issuer_counts = Counter(all_resolved)
        eligible_total = self._nonnegative_int(
            artifact.get("observationCount"), "cohort.observationCount"
        )
        if len(normalized_errors) > eligible_total:
            raise ValueError("Hay más forecast errors que outcomes elegibles en la cohorte.")
        return {
            "module": "research_forecast_error_oos_diagnostic",
            "status": (
                "forecast_error_oos_evidence_available"
                if normalized_errors
                else "forecast_error_oos_evidence_pending"
            ),
            "asOf": cutoff.isoformat(),
            "cohortId": artifact.get("cohortId"),
            "cohortHash": artifact.get("cohortHash"),
            "cohortAsOf": artifact.get("asOf"),
            "eligibleOutcomeCount": eligible_total,
            "forecastErrorCount": len(normalized_errors),
            "missingForecastErrorCount": eligible_total - len(normalized_errors),
            "measurementCoverage": (
                len(normalized_errors) / eligible_total if eligible_total else 0.0
            ),
            "resolvedIssuerErrorCount": len(all_resolved),
            "unresolvedIssuerErrorCount": len(normalized_errors) - len(all_resolved),
            "distinctResolvedIssuerCount": len(issuer_counts),
            "maximumErrorsPerResolvedIssuer": max(issuer_counts.values(), default=0),
            **self._longitudinal_summary(normalized_errors),
            "longitudinalSufficiency": {
                "status": "policy_not_precommitted",
                "policyId": None,
                "policyApproved": False,
                "productionSufficiencyClaimed": False,
            },
            "horizonCount": len(horizons),
            "horizons": horizons,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "measurement": "mae_mse_rmse_and_mean_signed_error_from_precommitted_forecasts",
                "forecastIntegrity": "each_error_hash_reverified_before_diagnostic_use",
                "cohortIntegrity": "issuer_aware_cohort_hash_reverified_before_join",
                "lookAhead": "cohort_and_error_persistence_must_be_available_at_or_before_diagnostic_as_of",
                "issuerDiversity": "distinct_resolved_issuers_reported_separately_from_error_count",
                "statisticalIndependence": "not_claimed",
                "horizonPooling": "forbidden_exact_elapsed_horizons_only",
                "skillClaim": "forbidden_descriptive_errors_are_not_proof_of_predictive_skill",
                "thresholds": "none_selected_here",
                "longitudinalSufficiency": "requires_separate_precommitted_approved_policy",
                "learningUse": "diagnostic_only_not_automatic_model_update",
            },
        }

    def _pending(self) -> dict[str, Any]:
        return {
            "module": "research_forecast_error_oos_diagnostic",
            "status": "forecast_error_oos_evidence_pending",
            "asOf": None,
            "cohortId": None,
            "cohortHash": None,
            "cohortAsOf": None,
            "eligibleOutcomeCount": 0,
            "forecastErrorCount": 0,
            "missingForecastErrorCount": 0,
            "measurementCoverage": 0.0,
            "resolvedIssuerErrorCount": 0,
            "unresolvedIssuerErrorCount": 0,
            "distinctResolvedIssuerCount": 0,
            "maximumErrorsPerResolvedIssuer": 0,
            "firstEvaluationPeriodEnd": None,
            "lastEvaluationPeriodEnd": None,
            "distinctEvaluationPeriodCount": 0,
            "evaluationSpanDays": 0.0,
            "longitudinalEvidenceStatus": "no_evaluated_periods",
            "longitudinalSufficiency": {
                "status": "policy_not_precommitted",
                "policyId": None,
                "policyApproved": False,
                "productionSufficiencyClaimed": False,
            },
            "horizonCount": 0,
            "horizons": {},
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "measurement": "mae_mse_rmse_and_mean_signed_error_from_precommitted_forecasts",
                "forecastIntegrity": "each_error_hash_reverified_before_diagnostic_use",
                "cohortIntegrity": "issuer_aware_cohort_hash_reverified_before_join",
                "lookAhead": "cohort_and_error_persistence_must_be_available_at_or_before_diagnostic_as_of",
                "issuerDiversity": "distinct_resolved_issuers_reported_separately_from_error_count",
                "statisticalIndependence": "not_claimed",
                "horizonPooling": "forbidden_exact_elapsed_horizons_only",
                "skillClaim": "forbidden_descriptive_errors_are_not_proof_of_predictive_skill",
                "thresholds": "none_selected_here",
                "longitudinalSufficiency": "requires_separate_precommitted_approved_policy",
                "learningUse": "diagnostic_only_not_automatic_model_update",
            },
        }

    def _longitudinal_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "firstEvaluationPeriodEnd": None,
                "lastEvaluationPeriodEnd": None,
                "distinctEvaluationPeriodCount": 0,
                "evaluationSpanDays": 0.0,
                "longitudinalEvidenceStatus": "no_evaluated_periods",
            }
        period_ends = sorted(
            {
                self._aware_iso(item.get("periodEnd"), "error.periodEnd")
                for item in rows
            }
        )
        first = period_ends[0]
        last = period_ends[-1]
        span_days = (last - first).total_seconds() / 86400.0
        return {
            "firstEvaluationPeriodEnd": first.isoformat(),
            "lastEvaluationPeriodEnd": last.isoformat(),
            "distinctEvaluationPeriodCount": len(period_ends),
            "evaluationSpanDays": span_days,
            "longitudinalEvidenceStatus": (
                "multiple_evaluation_periods_observed"
                if len(period_ends) >= 2 and span_days > 0.0
                else "single_period_snapshot"
            ),
        }

    def _normalize_error(
        self, record: dict[str, Any], *, cutoff: datetime
    ) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("Forecast error record debe ser un objeto persistido.")
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Forecast error record perdió artifact.")
        if artifact.get("module") != "research_forecast_error":
            raise ValueError("Solo se admiten research_forecast_error canónicos.")
        self._assert_error_safe(artifact)
        error_hash = self._sha_text(artifact.get("errorHash"), "error.errorHash")
        if self._sha_text(record.get("error_hash"), "record.error_hash") != error_hash:
            raise ValueError("Forecast error record no coincide con errorHash.")
        created_at = self._aware_iso(record.get("created_at"), "error.created_at")
        if created_at > cutoff:
            raise ValueError("Forecast error fue persistido después del as_of diagnóstico.")
        return {
            "errorHash": error_hash,
            "specificationHash": self._sha_text(
                artifact.get("specificationHash"), "error.specificationHash"
            ),
            "outcomeHash": self._sha_text(
                artifact.get("outcomeHash"), "error.outcomeHash"
            ),
            "cycleHash": self._sha_text(artifact.get("cycleHash"), "error.cycleHash"),
            "instrumentId": self._text(artifact.get("instrumentId"), "error.instrumentId"),
            "symbol": self._text(artifact.get("symbol"), "error.symbol").upper(),
            "periodStart": self._text(artifact.get("periodStart"), "error.periodStart"),
            "periodEnd": self._text(artifact.get("periodEnd"), "error.periodEnd"),
            "horizonSeconds": self._positive_int(
                artifact.get("horizonSeconds"), "error.horizonSeconds"
            ),
            "expectedValue": self._finite(artifact.get("expectedValue"), "error.expectedValue"),
            "realizedValue": self._finite(artifact.get("realizedValue"), "error.realizedValue"),
            "signedError": self._finite(artifact.get("signedError"), "error.signedError"),
            "absoluteError": self._finite(artifact.get("absoluteError"), "error.absoluteError"),
            "squaredError": self._finite(artifact.get("squaredError"), "error.squaredError"),
        }

    def _assert_error_matches_cohort_row(
        self, error: dict[str, Any], row: dict[str, Any]
    ) -> None:
        comparisons = (
            ("cycleHash", "cycleHash"),
            ("instrumentId", "instrumentId"),
            ("symbol", "symbol"),
            ("periodStart", "periodStart"),
            ("periodEnd", "periodEnd"),
            ("horizonSeconds", "horizonSeconds"),
        )
        for error_key, row_key in comparisons:
            left = error.get(error_key)
            right = row.get(row_key)
            if error_key == "symbol":
                left = str(left).upper()
                right = str(right).upper()
            if left != right:
                raise ValueError(
                    f"Forecast error y fila OOS no coinciden en {error_key}."
                )
        realized = self._finite(row.get("totalReturn"), "cohort.totalReturn")
        if not math.isclose(
            float(error["realizedValue"]), realized, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("Forecast error realizedValue no coincide con el outcome OOS.")

    def _metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        signed = [self._finite(item["signedError"], "signedError") for item in rows]
        absolute = [self._finite(item["absoluteError"], "absoluteError") for item in rows]
        squared = [self._finite(item["squaredError"], "squaredError") for item in rows]
        expected = [self._finite(item["expectedValue"], "expectedValue") for item in rows]
        realized = [self._finite(item["realizedValue"], "realizedValue") for item in rows]
        count = len(rows)
        mse = sum(squared) / count
        metrics = {
            "meanSignedError": sum(signed) / count,
            "meanAbsoluteError": sum(absolute) / count,
            "meanSquaredError": mse,
            "rootMeanSquaredError": math.sqrt(mse),
            "meanExpectedValue": sum(expected) / count,
            "meanRealizedValue": sum(realized) / count,
        }
        for key, value in metrics.items():
            if not math.isfinite(value):
                raise ValueError(f"La métrica {key} no es finita.")
        return metrics

    def _assert_cohort_safe(self, artifact: dict[str, Any]) -> None:
        if artifact.get("module") != "research_outcome_oos_cohort":
            raise ValueError("Se requiere research_outcome_oos_cohort canónica.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La cohorte OOS perdió no_advice.")
        if artifact.get("productionEligible") is not False:
            raise ValueError("La cohorte OOS intentó habilitar producción.")
        if artifact.get("isWeightingReady") is not False:
            raise ValueError("La cohorte OOS intentó habilitar weighting.")
        if artifact.get("productionLearningEligible") is not False:
            raise ValueError("La cohorte OOS intentó habilitar learning productivo.")

    def _assert_error_safe(self, artifact: dict[str, Any]) -> None:
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Forecast error perdió no_advice.")
        for key in (
            "productionEligible",
            "isWeightingReady",
            "recommendationCandidateReady",
            "productionLearningEligible",
        ):
            if artifact.get(key) is not False:
                raise ValueError(f"Forecast error intentó activar {key}.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Forecast error perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("Forecast error intentó trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Forecast error intentó promoción automática.")
        if policy.get("automaticModelMutation") is not False:
            raise ValueError("Forecast error intentó mutar modelo automáticamente.")
        if policy.get("skillClaim") != "forbidden_single_observation_is_not_evidence_of_skill":
            raise ValueError("Forecast error intentó presentar una observación como skill.")

    def _aware_iso(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico finito.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _nonnegative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} debe ser entero no negativo.")
        return value

    def _sha_text(self, value: object, field: str) -> str:
        text = self._text(value, field).lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text
