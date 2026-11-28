from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
import math
import re
from typing import Any

from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_MODEL_MARKERS = ("financialmodelingprep", "financial modeling prep")


class RecommendationResearchModelExecutionReceiptService:
    """Bind one PIT-safe v3 forecast to the exact model execution that produced it.

    The receipt binds declared identity, temporal ordering and immutable output.
    It does not execute the model or prove that supplied artifact bytes exist.
    It deliberately makes no claim about model quality, predictive skill, production
    eligibility, weighting approval, or trading authority.
    """

    ARTIFACT_VERSION = "research-model-execution-receipt-v1"
    SPECIFICATION_VERSION = "research-evaluation-specification-v3"

    def __init__(
        self,
        specification_service: RecommendationResearchEvaluationSpecificationService | None = None,
        model_executor: Any = None,
    ) -> None:
        self._specification_service = (
            specification_service or RecommendationResearchEvaluationSpecificationService()
        )
        self._model_executor = model_executor

    @staticmethod
    def _v2_core(artifact: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "artifactVersion", "specificationHash", "cycleHash", "executionId", "executedAt",
            "model", "inputManifestHash", "output", "outputHash", "observation", "modelBytesBase64",
        )
        return {key: artifact.get(key) for key in keys}

    def build_observed(
        self, *, specification_record: dict[str, Any], observation: dict[str, Any], model_bytes: bytes,
    ) -> dict[str, Any]:
        receipt = self.build(
            specification_record=specification_record,
            execution_id=observation["executionId"], model_name=observation["model"]["name"],
            model_version=observation["model"]["version"],
            model_artifact_hash=observation["model"]["artifactHash"],
            executed_at=self._aware_iso(observation["executedAt"], "executedAt"),
        )
        receipt.update(
            artifactVersion="research-model-execution-receipt-v2",
            observation=observation,
            modelBytesBase64=base64.b64encode(model_bytes).decode("ascii"),
        )
        receipt["receiptHash"] = self._canonical_hash(self._v2_core(receipt))
        return self.validate_against_specification(artifact=receipt, specification_record=specification_record)

    def build(
        self,
        *,
        specification_record: dict[str, Any],
        execution_id: str,
        model_name: str,
        model_version: str,
        model_artifact_hash: str,
        executed_at: datetime,
    ) -> dict[str, Any]:
        specification = self._validated_specification_record(specification_record)
        execution = self._aware_utc(executed_at, "executed_at")
        forecast_available = self._aware_iso(
            specification["forecastEvidence"]["availableAt"],
            "forecastEvidence.availableAt",
        )
        inputs = specification.get("inputEvidence")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("El forecast v3 debe conservar inputEvidence no vacío.")
        latest_input = max(
            self._aware_iso(item.get("availableAt"), "inputEvidence.availableAt")
            for item in inputs
            if isinstance(item, dict)
        )
        if execution < latest_input:
            raise ValueError("La ejecución del modelo es anterior a un input utilizado.")
        if execution > forecast_available:
            raise ValueError("La ejecución del modelo es posterior a forecastEvidence.availableAt.")

        normalized_model_name = self._text(model_name, "model_name")
        normalized_model_version = self._text(model_version, "model_version")
        self._assert_model_allowed(normalized_model_name)
        self._assert_model_allowed(normalized_model_version)

        output = {
            "metric": "total_return",
            "expectedValue": self._finite(specification.get("expectedValue"), "expectedValue"),
        }
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "specificationHash": self._sha256(
                specification.get("specificationHash"), "specificationHash"
            ),
            "cycleHash": self._sha256(specification.get("cycleHash"), "cycleHash"),
            "executionId": self._text(execution_id, "execution_id"),
            "executedAt": execution.isoformat(),
            "model": {
                "name": normalized_model_name,
                "version": normalized_model_version,
                "artifactHash": self._sha256(model_artifact_hash, "model_artifact_hash"),
            },
            "inputManifestHash": self._canonical_hash(inputs),
            "output": output,
            "outputHash": self._canonical_hash(output),
        }
        return {
            "module": "research_model_execution_receipt",
            **core,
            "receiptHash": self._canonical_hash(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "productionLearningEligible": False,
            "recommendationCandidateReady": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "specificationVersion": self.SPECIFICATION_VERSION,
                "metricScope": "total_return_only_v1",
                "temporalOrder": "all_inputs_available_at_or_before_execution_at_or_before_forecast_available_at",
                "modelQualityClaim": "forbidden",
                "predictiveSkillClaim": "forbidden",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if isinstance(artifact, dict) and artifact.get("artifactVersion") == "research-model-execution-receipt-v2":
            if artifact.get("receiptHash") != self._canonical_hash(self._v2_core(artifact)):
                raise ValueError("El recibo v2 fue modificado después de persistirse.")
            base = dict(artifact)
            base["artifactVersion"] = self.ARTIFACT_VERSION
            base.pop("observation", None)
            base.pop("modelBytesBase64", None)
            core_keys = (
                "artifactVersion", "specificationHash", "cycleHash", "executionId", "executedAt",
                "model", "inputManifestHash", "output", "outputHash",
            )
            base["receiptHash"] = self._canonical_hash({key: base.get(key) for key in core_keys})
            self.validate_artifact(base)
            return artifact
        if not isinstance(artifact, dict):
            raise ValueError("Model execution receipt debe ser un objeto.")
        if artifact.get("module") != "research_model_execution_receipt":
            raise ValueError("Model execution receipt perdió module.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de model execution receipt no compatible.")
        self._assert_shadow(artifact)
        self._sha256(artifact.get("specificationHash"), "specificationHash")
        self._sha256(artifact.get("cycleHash"), "cycleHash")
        self._text(artifact.get("executionId"), "executionId")
        self._aware_iso(artifact.get("executedAt"), "executedAt")
        model = artifact.get("model")
        if not isinstance(model, dict):
            raise ValueError("Model execution receipt perdió model.")
        name = self._text(model.get("name"), "model.name")
        version = self._text(model.get("version"), "model.version")
        self._assert_model_allowed(name)
        self._assert_model_allowed(version)
        self._sha256(model.get("artifactHash"), "model.artifactHash")
        self._sha256(artifact.get("inputManifestHash"), "inputManifestHash")
        output = artifact.get("output")
        if not isinstance(output, dict) or output.get("metric") != "total_return":
            raise ValueError("Model execution receipt solo admite output total_return.")
        self._finite(output.get("expectedValue"), "output.expectedValue")
        if self._sha256(artifact.get("outputHash"), "outputHash") != self._canonical_hash(output):
            raise ValueError("Model execution receipt no coincide con outputHash.")
        policy = artifact.get("policy")
        required_policy = {
            "specificationVersion": self.SPECIFICATION_VERSION,
            "metricScope": "total_return_only_v1",
            "temporalOrder": "all_inputs_available_at_or_before_execution_at_or_before_forecast_available_at",
            "modelQualityClaim": "forbidden",
            "predictiveSkillClaim": "forbidden",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }
        if not isinstance(policy, dict) or any(policy.get(k) != v for k, v in required_policy.items()):
            raise ValueError("Model execution receipt violó su policy.")
        core_keys = (
            "artifactVersion",
            "specificationHash",
            "cycleHash",
            "executionId",
            "executedAt",
            "model",
            "inputManifestHash",
            "output",
            "outputHash",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._sha256(artifact.get("receiptHash"), "receiptHash") != self._canonical_hash(core):
            raise ValueError("Model execution receipt fue modificada tras crear receiptHash.")
        return artifact

    def validate_against_specification(
        self,
        *,
        artifact: dict[str, Any],
        specification_record: dict[str, Any],
        materialized_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt = self.validate_artifact(artifact)
        specification = self._validated_specification_record(specification_record)
        if receipt["artifactVersion"] == "research-model-execution-receipt-v2":
            encoded = receipt.get("modelBytesBase64")
            if not isinstance(encoded, str) or len(encoded) > 13_333_336:
                raise ValueError("Bytes de modelo v2 ausentes o sobredimensionados.")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("Bytes de modelo v2 inválidos.") from exc
            executor = self._model_executor
            if executor is None:
                from app.services.recommendation_research_model_executor_service import RecommendationResearchModelExecutorService
                executor = RecommendationResearchModelExecutorService(runner=None)
            observation = executor.validate_observation(
                observation=receipt.get("observation"), specification=specification, model_bytes=raw,
                materialized_snapshot=materialized_snapshot,
            )
            for field in ("specificationHash", "executionId", "executedAt", "model", "inputManifestHash", "output", "outputHash"):
                if receipt[field] != observation[field]:
                    raise ValueError("El recibo v2 no corresponde a su ejecución observada.")
        if receipt["specificationHash"] != specification["specificationHash"]:
            raise ValueError("El recibo no pertenece a la evaluation specification indicada.")
        if receipt["cycleHash"] != specification["cycleHash"]:
            raise ValueError("El recibo cambió cycleHash.")
        inputs = specification["inputEvidence"]
        if receipt["inputManifestHash"] != self._canonical_hash(inputs):
            raise ValueError("El manifiesto PIT del forecast cambió después de la ejecución.")
        expected_output = {
            "metric": "total_return",
            "expectedValue": self._finite(specification.get("expectedValue"), "expectedValue"),
        }
        if receipt["output"] != expected_output:
            raise ValueError("El output ejecutado no coincide con el forecast sellado.")
        execution = self._aware_iso(receipt["executedAt"], "executedAt")
        latest_input = max(
            self._aware_iso(item["availableAt"], "inputEvidence.availableAt") for item in inputs
        )
        forecast_available = self._aware_iso(
            specification["forecastEvidence"]["availableAt"],
            "forecastEvidence.availableAt",
        )
        if not latest_input <= execution <= forecast_available:
            raise ValueError("El recibo viola el orden temporal PIT de la ejecución.")
        return receipt

    def _validated_specification_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("specification_record debe ser persistido.")
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("specification_record perdió artifact.")
        specification = self._specification_service.validate_artifact(artifact)
        if specification.get("artifactVersion") != self.SPECIFICATION_VERSION:
            raise ValueError("Model execution receipt exige evaluation specification v3.")
        persisted_hash = self._sha256(record.get("specification_hash"), "record.specification_hash")
        if persisted_hash != specification.get("specificationHash"):
            raise ValueError("specification_record discrepa del specificationHash canónico.")
        sealed_at = self._aware_iso(record.get("created_at"), "specification.created_at")
        available_at = self._aware_iso(
            specification["forecastEvidence"]["availableAt"], "forecastEvidence.availableAt"
        )
        period_start = self._aware_iso(specification["periodStart"], "periodStart")
        if not available_at <= sealed_at <= period_start:
            raise ValueError("La specification viola el orden temporal de su sello físico.")
        return specification

    def _assert_shadow(self, artifact: dict[str, Any]) -> None:
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Model execution receipt perdió no_advice.")
        for field in (
            "productionEligible",
            "productionLearningEligible",
            "recommendationCandidateReady",
            "automaticProductionPromotion",
            "automaticTrading",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"Model execution receipt intentó activar {field}.")

    def _assert_model_allowed(self, value: str) -> None:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_MODEL_MARKERS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido en model execution receipt.")

    def _canonical_hash(self, payload: object) -> str:
        try:
            serialized = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El recibo contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

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
