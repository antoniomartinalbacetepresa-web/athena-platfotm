from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


class RecommendationResearchEvaluationSpecificationService:
    """Freeze one measurable ex-ante forecast against an exact Research Cycle.

    V1 fixes the evaluation period at cycle.asOf. V2 allows an explicitly later
    prospective start. V3 keeps that prospective contract and additionally binds
    the model inputs by content hash and PIT availability, without claiming input
    quality, predictive skill, production eligibility, or trading authority.
    """

    ARTIFACT_VERSION = "research-evaluation-specification-v1"
    PROSPECTIVE_ARTIFACT_VERSION = "research-evaluation-specification-v2"
    PIT_INPUT_ARTIFACT_VERSION = "research-evaluation-specification-v3"

    def build(
        self,
        *,
        specification_id: str,
        cycle_record: dict[str, Any],
        horizon_seconds: int,
        expected_total_return: float,
        available_at: datetime,
        source: str,
        source_ref: str,
        method: str,
        period_start: datetime | None = None,
        input_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        specification_id_normalized = self._text(specification_id, "specification_id")
        cycle = self._cycle(cycle_record)
        cycle_hash = self._sha256(cycle["integrity"]["cycleHash"], "cycleHash")
        if self._sha256(cycle_record.get("cycle_hash"), "cycle_record.cycle_hash") != cycle_hash:
            raise ValueError("cycle_record no coincide con cycleHash.")

        instrument_id = self._text(cycle.get("instrumentId"), "cycle.instrumentId")
        symbol = self._text(cycle.get("symbol"), "cycle.symbol").upper()
        cycle_as_of = self._aware_iso(cycle.get("asOf"), "cycle.asOf")
        horizon = self._positive_int(horizon_seconds, "horizon_seconds")
        forecast = self._finite(expected_total_return, "expected_total_return")
        evidence_available_at = self._aware_utc(available_at, "available_at")
        prospective = period_start is not None
        if input_evidence is not None and not prospective:
            raise ValueError("input_evidence PIT solo se admite en un periodo prospectivo explícito.")
        start = self._aware_utc(period_start, "period_start") if prospective else cycle_as_of
        if prospective and start <= cycle_as_of:
            raise ValueError("El periodo prospectivo debe comenzar después de cycle.asOf.")
        if evidence_available_at > start:
            boundary = "period_start" if prospective else "cycle.asOf"
            raise ValueError(f"La previsión debe estar disponible a más tardar en {boundary}.")
        normalized_source = self._text(source, "source")
        normalized_source_ref = self._text(source_ref, "source_ref")
        normalized_method = self._text(method, "method")
        self._assert_source_allowed(normalized_source)
        self._assert_source_allowed(normalized_source_ref)

        normalized_inputs = None
        version = self.ARTIFACT_VERSION
        if prospective:
            version = self.PROSPECTIVE_ARTIFACT_VERSION
        if input_evidence is not None:
            normalized_inputs = self._normalize_input_evidence(
                input_evidence,
                forecast_available_at=evidence_available_at,
            )
            version = self.PIT_INPUT_ARTIFACT_VERSION

        period_end = start + timedelta(seconds=horizon)
        core = {
            "artifactVersion": version,
            "specificationId": specification_id_normalized,
            "cycleHash": cycle_hash,
            "instrumentId": instrument_id,
            "symbol": symbol,
            "cycleAsOf": cycle_as_of.isoformat(),
            "metric": "total_return",
            "periodStart": start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "horizonSeconds": horizon,
            "expectedValue": forecast,
            "forecastEvidence": {
                "availableAt": evidence_available_at.isoformat(),
                "source": normalized_source,
                "sourceRef": normalized_source_ref,
                "method": normalized_method,
            },
        }
        if normalized_inputs is not None:
            core["inputEvidence"] = normalized_inputs
        specification_hash = self._canonical_hash(core)
        policy = {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "targetDefinition": "precommitted_before_or_at_prospective_period_start" if prospective else "precommitted_before_or_at_frozen_cycle_as_of",
            "metricScope": "total_return_only_v1",
            "period": "starts_after_cycle_as_of_with_exact_elapsed_horizon" if prospective else "starts_exactly_at_cycle_as_of_with_exact_elapsed_horizon",
            "postOutcomeEditing": "forbidden_append_only_persistence_required",
            "evaluation": "signed_and_absolute_error_only_no_hit_rate_or_skill_claim",
            "thresholds": "none_selected_here",
            "causalClaim": "forbidden",
        }
        if normalized_inputs is not None:
            policy.update(
                {
                    "inputProvenance": "content_hash_bound_inputs_available_before_forecast_output",
                    "inputQualityClaim": "forbidden",
                }
            )
        return {
            "module": "research_evaluation_specification",
            **core,
            "specificationHash": specification_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": policy,
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("Evaluation specification debe ser un objeto.")
        if artifact.get("module") != "research_evaluation_specification":
            raise ValueError("Evaluation specification perdió module.")
        version = artifact.get("artifactVersion")
        allowed_versions = (
            self.ARTIFACT_VERSION,
            self.PROSPECTIVE_ARTIFACT_VERSION,
            self.PIT_INPUT_ARTIFACT_VERSION,
        )
        if version not in allowed_versions:
            raise ValueError("Versión de evaluation specification no compatible.")
        prospective = version in (self.PROSPECTIVE_ARTIFACT_VERSION, self.PIT_INPUT_ARTIFACT_VERSION)
        pit_inputs = version == self.PIT_INPUT_ARTIFACT_VERSION
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Evaluation specification perdió no_advice.")
        for field in (
            "productionEligible",
            "isWeightingReady",
            "recommendationCandidateReady",
            "productionLearningEligible",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"Evaluation specification intentó activar {field}.")
        if artifact.get("metric") != "total_return":
            raise ValueError("Evaluation specification solo admite total_return.")
        self._positive_int(artifact.get("horizonSeconds"), "horizonSeconds")
        self._finite(artifact.get("expectedValue"), "expectedValue")
        cycle_as_of = self._aware_iso(artifact.get("cycleAsOf"), "cycleAsOf")
        period_start = self._aware_iso(artifact.get("periodStart"), "periodStart")
        period_end = self._aware_iso(artifact.get("periodEnd"), "periodEnd")
        if prospective and period_start <= cycle_as_of:
            raise ValueError("periodStart prospectivo debe ser posterior a cycleAsOf.")
        if not prospective and period_start != cycle_as_of:
            raise ValueError("periodStart debe coincidir exactamente con cycleAsOf.")
        if (period_end - period_start).total_seconds() != artifact["horizonSeconds"]:
            raise ValueError("periodEnd no coincide con horizonSeconds.")
        evidence = artifact.get("forecastEvidence")
        if not isinstance(evidence, dict):
            raise ValueError("Evaluation specification perdió forecastEvidence.")
        available_at = self._aware_iso(evidence.get("availableAt"), "forecastEvidence.availableAt")
        if available_at > period_start:
            boundary = "periodStart" if prospective else "cycleAsOf"
            raise ValueError(f"forecastEvidence introduce hindsight respecto a {boundary}.")
        source = self._text(evidence.get("source"), "forecastEvidence.source")
        source_ref = self._text(evidence.get("sourceRef"), "forecastEvidence.sourceRef")
        self._text(evidence.get("method"), "forecastEvidence.method")
        self._assert_source_allowed(source)
        self._assert_source_allowed(source_ref)

        normalized_inputs = None
        if pit_inputs:
            raw_inputs = artifact.get("inputEvidence")
            normalized_inputs = self._normalize_input_evidence(
                raw_inputs,
                forecast_available_at=available_at,
            )
            if raw_inputs != normalized_inputs:
                raise ValueError("inputEvidence no está en forma canónica.")
        elif "inputEvidence" in artifact:
            raise ValueError("inputEvidence requiere el contrato prospectivo v3.")

        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Evaluation specification perdió policy.")
        required_policy = {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "targetDefinition": "precommitted_before_or_at_prospective_period_start" if prospective else "precommitted_before_or_at_frozen_cycle_as_of",
            "period": "starts_after_cycle_as_of_with_exact_elapsed_horizon" if prospective else "starts_exactly_at_cycle_as_of_with_exact_elapsed_horizon",
            "metricScope": "total_return_only_v1",
            "postOutcomeEditing": "forbidden_append_only_persistence_required",
            "thresholds": "none_selected_here",
            "causalClaim": "forbidden",
        }
        if pit_inputs:
            required_policy.update(
                {
                    "inputProvenance": "content_hash_bound_inputs_available_before_forecast_output",
                    "inputQualityClaim": "forbidden",
                }
            )
        for key, expected in required_policy.items():
            if policy.get(key) != expected:
                raise ValueError(f"Evaluation specification violó policy.{key}.")

        core_keys = [
            "artifactVersion",
            "specificationId",
            "cycleHash",
            "instrumentId",
            "symbol",
            "cycleAsOf",
            "metric",
            "periodStart",
            "periodEnd",
            "horizonSeconds",
            "expectedValue",
            "forecastEvidence",
        ]
        if pit_inputs:
            core_keys.append("inputEvidence")
        core = {key: artifact.get(key) for key in core_keys}
        expected_hash = self._canonical_hash(core)
        if self._sha256(artifact.get("specificationHash"), "specificationHash") != expected_hash:
            raise ValueError("Evaluation specification fue modificada tras crear specificationHash.")
        self._sha256(artifact.get("cycleHash"), "cycleHash")
        self._text(artifact.get("instrumentId"), "instrumentId")
        self._text(artifact.get("symbol"), "symbol")
        self._text(artifact.get("specificationId"), "specificationId")
        return artifact

    def _normalize_input_evidence(
        self,
        value: object,
        *,
        forecast_available_at: datetime,
    ) -> list[dict[str, str]]:
        if not isinstance(value, list) or not value:
            raise ValueError("inputEvidence debe contener al menos una entrada PIT verificable.")
        normalized: list[dict[str, str]] = []
        seen_hashes: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"inputEvidence[{index}] debe ser un objeto.")
            source = self._text(item.get("source"), f"inputEvidence[{index}].source")
            source_ref = self._text(item.get("sourceRef"), f"inputEvidence[{index}].sourceRef")
            self._assert_source_allowed(source)
            self._assert_source_allowed(source_ref)
            available_at = self._aware_iso(
                item.get("availableAt"),
                f"inputEvidence[{index}].availableAt",
            )
            if available_at > forecast_available_at:
                raise ValueError(
                    f"inputEvidence[{index}] no estaba disponible al generar la previsión."
                )
            content_hash = self._sha256(
                item.get("contentHash"),
                f"inputEvidence[{index}].contentHash",
            )
            if content_hash in seen_hashes:
                raise ValueError("inputEvidence contiene contentHash duplicado.")
            seen_hashes.add(content_hash)
            normalized.append(
                {
                    "source": source,
                    "sourceRef": source_ref,
                    "availableAt": available_at.isoformat(),
                    "contentHash": content_hash,
                }
            )
        return normalized

    def _cycle(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("cycle_record debe ser un registro persistido válido.")
        package = record.get("package")
        if not isinstance(package, dict):
            raise ValueError("cycle_record perdió package.")
        cycle = package.get("cycle")
        if not isinstance(cycle, dict):
            raise ValueError("cycle_record perdió cycle canónico.")
        if cycle.get("advisoryStatus") != "no_advice":
            raise ValueError("Research Cycle perdió no_advice.")
        if cycle.get("productionEligible") is not False or cycle.get("isWeightingReady") is not False:
            raise ValueError("Research Cycle intentó habilitar producción o weighting.")
        integrity = cycle.get("integrity")
        if not isinstance(integrity, dict):
            raise ValueError("Research Cycle perdió integrity.")
        policy = cycle.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Research Cycle perdió policy.")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Research Cycle perdió su contrato de seguridad.")
        return cycle

    def _assert_source_allowed(self, value: str) -> None:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido en evaluation specification.")

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser un entero positivo.")
        return value

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

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

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
