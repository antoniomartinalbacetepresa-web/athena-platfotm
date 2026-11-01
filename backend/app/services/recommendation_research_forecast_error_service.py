from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any


from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from app.services.recommendation_performance_attribution_service import (
    RecommendationPerformanceAttributionService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchForecastErrorService:
    """Compare one persisted ex-ante specification with one persisted outcome."""

    ARTIFACT_VERSION = "research-forecast-error-v1"

    def evaluate(
        self,
        *,
        specification_record: dict[str, Any],
        outcome_record: dict[str, Any],
    ) -> dict[str, Any]:
        specification = self._artifact(specification_record, "specification")
        outcome = self._artifact(outcome_record, "outcome")

        if specification.get("module") != "research_evaluation_specification":
            raise ValueError("Se requiere una evaluation specification canónica.")
        if outcome.get("module") != "research_outcome_attribution":
            raise ValueError("Se requiere un research outcome attribution canónico.")
        self._assert_research_only(specification, "specification")
        self._assert_research_only(outcome, "outcome")
        # Comparing two copies of a claimed hash is not content verification.
        RecommendationResearchEvaluationSpecificationService().validate_artifact(
            specification
        )

        specification_hash = self._sha256(
            specification.get("specificationHash"), "specificationHash"
        )
        if self._sha256(
            specification_record.get("specification_hash"),
            "specification_record.specification_hash",
        ) != specification_hash:
            raise ValueError("El registro de specification no coincide con specificationHash.")
        outcome_hash = self._sha256(outcome.get("outcomeHash"), "outcomeHash")
        if self._sha256(outcome_record.get("outcome_hash"), "outcome_record.outcome_hash") != outcome_hash:
            raise ValueError("El registro de outcome no coincide con outcomeHash.")
        canonical_outcome = {
            "outcomeId": outcome.get("outcomeId"),
            "cycleHash": outcome.get("cycleHash"),
            "instrumentId": outcome.get("instrumentId"),
            "symbol": outcome.get("symbol"),
            "cycleAsOf": outcome.get("cycleAsOf"),
            "attribution": outcome.get("attribution"),
        }
        if self._canonical_hash(canonical_outcome) != outcome_hash:
            raise ValueError("El contenido original del outcome no coincide con outcomeHash.")

        cycle_hash = self._sha256(specification.get("cycleHash"), "specification.cycleHash")
        if self._sha256(outcome.get("cycleHash"), "outcome.cycleHash") != cycle_hash:
            raise ValueError("Specification y outcome pertenecen a Research Cycles distintos.")
        if str(specification.get("instrumentId")) != str(outcome.get("instrumentId")):
            raise ValueError("Specification y outcome no coinciden en instrumentId.")
        if str(specification.get("symbol")).upper() != str(outcome.get("symbol")).upper():
            raise ValueError("Specification y outcome no coinciden en symbol.")
        if specification.get("metric") != "total_return":
            raise ValueError("Forecast error v1 solo admite total_return.")
        if str(specification.get("periodStart")) != str(outcome.get("periodStart")):
            raise ValueError("El outcome no comienza en el periodo precomprometido.")
        if str(specification.get("periodEnd")) != str(outcome.get("periodEnd")):
            raise ValueError("El outcome no termina en el periodo precomprometido.")

        attribution = outcome.get("attribution")
        if not isinstance(attribution, dict):
            raise ValueError("El outcome perdió Performance Attribution.")
        for field in ("instrumentId", "symbol", "periodStart", "periodEnd"):
            left, right = attribution.get(field), outcome.get(field)
            if field == "symbol" and isinstance(left, str) and isinstance(right, str):
                left, right = left.upper(), right.upper()
            if left != right:
                raise ValueError(f"Performance Attribution no coincide con outcome.{field}.")
        period_start = self._aware_iso(outcome.get("periodStart"), "outcome.periodStart")
        period_end = self._aware_iso(outcome.get("periodEnd"), "outcome.periodEnd")
        outcome_as_of = self._aware_iso(outcome.get("asOf"), "outcome.asOf")
        cycle_as_of = self._aware_iso(outcome.get("cycleAsOf"), "outcome.cycleAsOf")
        if period_start < cycle_as_of or period_end <= period_start or period_end > outcome_as_of:
            raise ValueError("Outcome contiene periodo o disponibilidad temporal inválidos.")
        if self._aware_iso(attribution.get("asOf"), "attribution.asOf") != outcome_as_of:
            raise ValueError("Performance Attribution no coincide con outcome.asOf.")

        # The canonical currency-pair producer binds a second, independent
        # attribution identity. Rehashing the outer outcome cannot validate
        # forged nested returns, FX, benchmarks or source capture metadata.
        attribution_policy = attribution.get("policy")
        outcome_policy = outcome.get("policy")
        canonical_fx = "explicit_currency_pair_bound_fail_closed"
        if (
            (isinstance(attribution_policy, dict) and attribution_policy.get("fx") == canonical_fx)
            or (isinstance(outcome_policy, dict) and outcome_policy.get("fx") == canonical_fx)
        ):
            if (
                not isinstance(attribution_policy, dict)
                or not isinstance(outcome_policy, dict)
                or attribution_policy.get("fx") != canonical_fx
                or outcome_policy.get("fx") != canonical_fx
            ):
                raise ValueError("Outcome y Performance Attribution no coinciden en FX canónico.")
            if outcome.get("currency") != attribution.get("currency"):
                raise ValueError("Outcome perdió identidad FX canónica.")
            if self._sha256(outcome.get("attributionKey"), "outcome.attributionKey") != self._sha256(
                attribution.get("attributionKey"), "attribution.attributionKey"
            ):
                raise ValueError("Outcome perdió attributionKey canónica.")
            if (
                not isinstance(outcome.get("benchmarkId"), str)
                or not outcome["benchmarkId"].strip()
                or outcome["benchmarkId"] != attribution.get("benchmarkId")
            ):
                raise ValueError("Outcome perdió benchmarkId canónico.")
            RecommendationPerformanceAttributionService.verify_canonical_payload(attribution)
            evidence = attribution.get("evidence")
            if not isinstance(evidence, dict) or not isinstance(evidence.get("factorContributions"), dict):
                raise ValueError("Performance Attribution perdió provenance canónica.")
            metas = [evidence.get(key) for key in ("totalReturn", "marketContribution", "fxContribution")]
            metas.extend(evidence["factorContributions"].values())
            seen_sources: set[tuple[str, str]] = set()
            for meta in metas:
                if not isinstance(meta, dict):
                    raise ValueError("Performance Attribution perdió provenance de un componente.")
                available_at = self._aware_iso(meta.get("availableAt"), "attribution.evidence.availableAt")
                if available_at < period_end or available_at > outcome_as_of:
                    raise ValueError("Evidencia de outcome disponible antes de cerrar el periodo o después de asOf.")
                source_key: list[str] = []
                for field in ("source", "sourceRef"):
                    value = meta.get(field)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("Evidencia de outcome carece de fuente verificable.")
                    normalized = value.casefold().replace("_", " ").replace("-", " ")
                    if normalized.replace(" ", "") == "fmp" or any(
                        forbidden in normalized
                        for forbidden in ("financialmodelingprep", "financial modeling prep")
                    ):
                        raise ValueError("FMP/Financial Modeling Prep está prohibido en outcomes.")
                    source_key.append(value.casefold())
                identity = (source_key[0], source_key[1])
                if identity in seen_sources:
                    raise ValueError("Evidencia de outcome contiene provenance duplicada.")
                seen_sources.add(identity)
        # Repositories remain authoritative for mandatory physical timestamps.
        if "created_at" in specification_record:
            sealed_at = self._aware_iso(specification_record["created_at"], "specification.created_at")
            available_at = self._aware_iso(
                specification["forecastEvidence"]["availableAt"], "forecastEvidence.availableAt"
            )
            if sealed_at > period_start or sealed_at < available_at:
                raise ValueError("Specification no fue sellada ex-ante con evidencia disponible.")
        if "created_at" in outcome_record:
            persisted_at = self._aware_iso(outcome_record["created_at"], "outcome.created_at")
            if persisted_at < outcome_as_of:
                raise ValueError("Outcome fue persistido antes de su observación.")
        expected = self._finite(specification.get("expectedValue"), "expectedValue")
        realized = self._finite(attribution.get("totalReturn"), "realizedTotalReturn")
        signed_error = realized - expected
        absolute_error = abs(signed_error)
        squared_error = signed_error * signed_error
        for name, value in (
            ("signedError", signed_error),
            ("absoluteError", absolute_error),
            ("squaredError", squared_error),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} debe ser finito.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "specificationHash": specification_hash,
            "outcomeHash": outcome_hash,
            "cycleHash": cycle_hash,
            "instrumentId": specification["instrumentId"],
            "symbol": str(specification["symbol"]).upper(),
            "metric": "total_return",
            "periodStart": specification["periodStart"],
            "periodEnd": specification["periodEnd"],
            "horizonSeconds": specification["horizonSeconds"],
            "expectedValue": expected,
            "realizedValue": realized,
            "signedError": signed_error,
            "absoluteError": absolute_error,
            "squaredError": squared_error,
        }
        error_hash = self._canonical_hash(core)
        return {
            "module": "research_forecast_error",
            **core,
            "errorHash": error_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "comparison": "exact_precommitted_specification_vs_exact_persisted_outcome",
                "metric": "signed_absolute_and_squared_error_only",
                "skillClaim": "forbidden_single_observation_is_not_evidence_of_skill",
                "thresholds": "none_selected_here",
                "hindsight": "forbidden_specification_must_predate_outcome_and_match_exact_period",
                "causalClaim": "forbidden",
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("module") != "research_forecast_error":
            raise ValueError("Forecast error artifact inválido.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de forecast error no compatible.")
        self._assert_research_only(artifact, "forecast_error")
        for field in ("productionLearningEligible", "recommendationCandidateReady"):
            if artifact.get(field) is not False:
                raise ValueError(f"Forecast error intentó activar {field}.")
        expected = self._finite(artifact.get("expectedValue"), "expectedValue")
        realized = self._finite(artifact.get("realizedValue"), "realizedValue")
        signed = self._finite(artifact.get("signedError"), "signedError")
        absolute = self._finite(artifact.get("absoluteError"), "absoluteError")
        squared = self._finite(artifact.get("squaredError"), "squaredError")
        if not math.isclose(signed, realized - expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("signedError no reconcilia con realized - expected.")
        if not math.isclose(absolute, abs(signed), rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("absoluteError no reconcilia con signedError.")
        if not math.isclose(squared, signed * signed, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("squaredError no reconcilia con signedError.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Forecast error perdió policy.")
        if policy.get("automaticModelMutation") is not False:
            raise ValueError("Forecast error intentó mutar el modelo automáticamente.")
        if policy.get("skillClaim") != "forbidden_single_observation_is_not_evidence_of_skill":
            raise ValueError("Forecast error intentó convertir una observación en skill.")
        core_keys = (
            "artifactVersion",
            "specificationHash",
            "outcomeHash",
            "cycleHash",
            "instrumentId",
            "symbol",
            "metric",
            "periodStart",
            "periodEnd",
            "horizonSeconds",
            "expectedValue",
            "realizedValue",
            "signedError",
            "absoluteError",
            "squaredError",
        )
        if self._canonical_hash({key: artifact.get(key) for key in core_keys}) != self._sha256(
            artifact.get("errorHash"), "errorHash"
        ):
            raise ValueError("Forecast error fue modificado tras crear errorHash.")
        return artifact

    def _aware_iso(self, value: object, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field} debe ser ISO-8601 con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _artifact(self, record: dict[str, Any], name: str) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError(f"{name}_record debe ser un registro persistido.")
        artifact = record.get("artifact") if name == "specification" else record.get("payload")
        if not isinstance(artifact, dict):
            raise ValueError(f"{name}_record perdió su artifact/payload.")
        return artifact

    def _assert_research_only(self, payload: dict[str, Any], name: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{name} perdió no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{name} intentó habilitar producción.")
        if payload.get("isWeightingReady") is not False:
            raise ValueError(f"{name} intentó habilitar weighting.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError(f"{name} perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError(f"{name} intentó trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError(f"{name} intentó promoción automática.")

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
