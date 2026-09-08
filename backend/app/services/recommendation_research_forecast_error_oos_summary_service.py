from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from statistics import median
from typing import Any, Sequence

from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from app.services.recommendation_research_forecast_error_service import (
    RecommendationResearchForecastErrorService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchForecastErrorOosSummaryService:
    """Build a descriptive, PIT-safe OOS summary from persisted forecast errors.

    The summary intentionally makes no skill/readiness decision. It only aggregates
    tamper-verified errors produced by one explicit forecast method at one exact
    horizon, reports overlap/repetition diagnostics, and keeps all production,
    recommendation and automatic-learning gates closed.
    """

    ARTIFACT_VERSION = "research-forecast-error-oos-summary-v1"

    def __init__(self) -> None:
        self._error_service = RecommendationResearchForecastErrorService()
        self._specification_service = RecommendationResearchEvaluationSpecificationService()

    def build(
        self,
        *,
        summary_id: str,
        as_of: datetime,
        error_records: Sequence[dict[str, Any]],
        specification_records: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_id = self._text(summary_id, "summary_id")
        cutoff = self._aware_utc(as_of, "as_of")
        if not error_records:
            raise ValueError("error_records debe contener al menos un forecast error persistido.")
        if len(error_records) > 5000:
            raise ValueError("error_records supera el límite de investigación de 5000 filas.")
        if len(error_records) != len(specification_records):
            raise ValueError("Cada forecast error requiere exactamente su specification persistida.")

        specs_by_hash: dict[str, dict[str, Any]] = {}
        for record in specification_records:
            artifact = record.get("artifact") if isinstance(record, dict) else None
            if not isinstance(artifact, dict):
                raise ValueError("Specification record inválido.")
            self._specification_service.validate_artifact(artifact)
            spec_hash = self._sha256(artifact.get("specificationHash"), "specificationHash")
            persisted_hash = self._sha256(record.get("specification_hash"), "record.specification_hash")
            if spec_hash != persisted_hash:
                raise ValueError("Specification persistida no coincide con specificationHash.")
            if spec_hash in specs_by_hash:
                raise ValueError("specification_records contiene specificationHash duplicado.")
            self._assert_created_by_cutoff(record, cutoff, "specification")
            specs_by_hash[spec_hash] = artifact

        rows: list[dict[str, Any]] = []
        seen_errors: set[str] = set()
        seen_outcomes: set[str] = set()
        seen_cycles: set[str] = set()
        methods: set[str] = set()
        horizons: set[int] = set()

        for record in error_records:
            if not isinstance(record, dict):
                raise ValueError("Cada forecast error debe ser un registro persistido.")
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("Forecast error persistido carece de artifact.")
            self._error_service.validate_artifact(artifact)
            error_hash = self._sha256(artifact.get("errorHash"), "errorHash")
            if self._sha256(record.get("error_hash"), "record.error_hash") != error_hash:
                raise ValueError("Forecast error persistido no coincide con errorHash.")
            if error_hash in seen_errors:
                raise ValueError("error_records contiene errorHash duplicado.")
            seen_errors.add(error_hash)
            self._assert_created_by_cutoff(record, cutoff, "forecast_error")

            spec_hash = self._sha256(artifact.get("specificationHash"), "specificationHash")
            specification = specs_by_hash.get(spec_hash)
            if specification is None:
                raise ValueError("Falta la specification persistida de un forecast error.")
            if str(specification.get("cycleHash")) != str(artifact.get("cycleHash")):
                raise ValueError("Forecast error y specification no coinciden en cycleHash.")
            if str(specification.get("periodStart")) != str(artifact.get("periodStart")) or str(
                specification.get("periodEnd")
            ) != str(artifact.get("periodEnd")):
                raise ValueError("Forecast error y specification no coinciden en periodo.")

            evidence = specification.get("forecastEvidence")
            if not isinstance(evidence, dict):
                raise ValueError("Specification perdió forecastEvidence.")
            method = self._text(evidence.get("method"), "forecastEvidence.method")
            horizon = self._positive_int(artifact.get("horizonSeconds"), "horizonSeconds")
            methods.add(method)
            horizons.add(horizon)

            outcome_hash = self._sha256(artifact.get("outcomeHash"), "outcomeHash")
            cycle_hash = self._sha256(artifact.get("cycleHash"), "cycleHash")
            if outcome_hash in seen_outcomes:
                raise ValueError("La cohorte reutiliza el mismo outcomeHash.")
            if cycle_hash in seen_cycles:
                raise ValueError("La cohorte reutiliza el mismo Research Cycle.")
            seen_outcomes.add(outcome_hash)
            seen_cycles.add(cycle_hash)

            period_start = self._aware_iso(artifact.get("periodStart"), "periodStart")
            period_end = self._aware_iso(artifact.get("periodEnd"), "periodEnd")
            if period_end <= period_start or period_end > cutoff:
                raise ValueError("Forecast error contiene periodo posterior o inválido para summary asOf.")
            signed = self._finite(artifact.get("signedError"), "signedError")
            absolute = self._finite(artifact.get("absoluteError"), "absoluteError")
            squared = self._finite(artifact.get("squaredError"), "squaredError")
            rows.append(
                {
                    "errorHash": error_hash,
                    "specificationHash": spec_hash,
                    "outcomeHash": outcome_hash,
                    "cycleHash": cycle_hash,
                    "instrumentId": self._text(artifact.get("instrumentId"), "instrumentId"),
                    "symbol": self._text(artifact.get("symbol"), "symbol").upper(),
                    "periodStart": period_start.isoformat(),
                    "periodEnd": period_end.isoformat(),
                    "horizonSeconds": horizon,
                    "expectedValue": self._finite(artifact.get("expectedValue"), "expectedValue"),
                    "realizedValue": self._finite(artifact.get("realizedValue"), "realizedValue"),
                    "signedError": signed,
                    "absoluteError": absolute,
                    "squaredError": squared,
                    "method": method,
                }
            )

        if len(methods) != 1:
            raise ValueError("OOS summary no puede mezclar métodos de forecast distintos.")
        if len(horizons) != 1:
            raise ValueError("OOS summary no puede mezclar horizontes distintos.")
        if set(specs_by_hash) != {str(row["specificationHash"]) for row in rows}:
            raise ValueError("specification_records contiene specifications ajenas a la cohorte.")

        rows.sort(key=lambda row: (str(row["periodEnd"]), str(row["instrumentId"]), str(row["errorHash"])))
        signed_values = [float(row["signedError"]) for row in rows]
        absolute_values = [float(row["absoluteError"]) for row in rows]
        squared_values = [float(row["squaredError"]) for row in rows]
        count = len(rows)
        mean_signed_error = self._finite(sum(signed_values) / count, "meanSignedError")
        mae = self._finite(sum(absolute_values) / count, "meanAbsoluteError")
        rmse = self._finite(math.sqrt(sum(squared_values) / count), "rootMeanSquaredError")
        median_absolute_error = self._finite(median(absolute_values), "medianAbsoluteError")

        overlap_pairs = 0
        for index, left in enumerate(rows):
            left_start = self._aware_iso(left["periodStart"], "row.periodStart")
            left_end = self._aware_iso(left["periodEnd"], "row.periodEnd")
            for right in rows[index + 1 :]:
                right_start = self._aware_iso(right["periodStart"], "row.periodStart")
                right_end = self._aware_iso(right["periodEnd"], "row.periodEnd")
                if max(left_start, right_start) < min(left_end, right_end):
                    overlap_pairs += 1

        instrument_counts = Counter(str(row["instrumentId"]) for row in rows)
        method = next(iter(methods))
        horizon = next(iter(horizons))
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "summaryId": normalized_id,
            "asOf": cutoff.isoformat(),
            "method": method,
            "horizonSeconds": horizon,
            "observationCount": count,
            "distinctInstrumentCount": len(instrument_counts),
            "maximumObservationsPerInstrument": max(instrument_counts.values(), default=0),
            "overlappingPeriodPairCount": overlap_pairs,
            "metrics": {
                "meanSignedError": mean_signed_error,
                "meanAbsoluteError": mae,
                "rootMeanSquaredError": rmse,
                "medianAbsoluteError": median_absolute_error,
            },
            "errorHashes": [str(row["errorHash"]) for row in rows],
            "rows": rows,
        }
        summary_hash = self._canonical_hash(core)
        return {
            "module": "research_forecast_error_oos_summary",
            **core,
            "summaryHash": summary_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "learningResearchDatasetReady": True,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "lookAhead": "only_persisted_errors_and_specifications_created_at_or_before_summary_as_of",
                "comparability": "single_explicit_method_and_exact_horizon_required",
                "periodOverlap": "reported_not_silently_treated_as_independent",
                "statisticalIndependence": "not_claimed",
                "skillClaim": "forbidden_descriptive_errors_do_not_establish_skill",
                "thresholdCalibration": "not_calibrated",
                "recommendationReadiness": "not_established",
                "learningUse": "research_only_no_automatic_model_update",
                "causalClaim": "forbidden",
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("module") != "research_forecast_error_oos_summary":
            raise ValueError("OOS forecast summary inválido.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de OOS forecast summary incompatible.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("OOS forecast summary perdió no_advice.")
        for field in ("productionEligible", "isWeightingReady", "recommendationCandidateReady", "productionLearningEligible"):
            if artifact.get(field) is not False:
                raise ValueError(f"OOS forecast summary intentó activar {field}.")
        if artifact.get("learningResearchDatasetReady") is not True:
            raise ValueError("OOS forecast summary perdió uso research-only.")
        metrics = artifact.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("OOS forecast summary perdió metrics.")
        for name in ("meanSignedError", "meanAbsoluteError", "rootMeanSquaredError", "medianAbsoluteError"):
            self._finite(metrics.get(name), f"metrics.{name}")
        policy = artifact.get("policy")
        required = {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "statisticalIndependence": "not_claimed",
            "skillClaim": "forbidden_descriptive_errors_do_not_establish_skill",
            "thresholdCalibration": "not_calibrated",
            "recommendationReadiness": "not_established",
            "learningUse": "research_only_no_automatic_model_update",
            "causalClaim": "forbidden",
        }
        if not isinstance(policy, dict):
            raise ValueError("OOS forecast summary perdió policy.")
        for key, expected in required.items():
            if policy.get(key) != expected:
                raise ValueError(f"OOS forecast summary violó policy.{key}.")
        core_keys = (
            "artifactVersion", "summaryId", "asOf", "method", "horizonSeconds",
            "observationCount", "distinctInstrumentCount", "maximumObservationsPerInstrument",
            "overlappingPeriodPairCount", "metrics", "errorHashes", "rows",
        )
        expected_hash = self._canonical_hash({key: artifact.get(key) for key in core_keys})
        if self._sha256(artifact.get("summaryHash"), "summaryHash") != expected_hash:
            raise ValueError("OOS forecast summary fue modificado tras crear summaryHash.")
        return artifact

    def _assert_created_by_cutoff(self, record: dict[str, Any], cutoff: datetime, name: str) -> None:
        created_at = self._aware_iso(record.get("created_at"), f"{name}.created_at")
        if created_at > cutoff:
            raise ValueError(f"{name} introduce look-ahead respecto a summary asOf.")

    @staticmethod
    def _canonical_hash(payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _aware_iso(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text
