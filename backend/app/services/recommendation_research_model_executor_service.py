from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Callable, Protocol
from uuid import uuid4

from app.services.persisted_forecast_input_manifest_service import PersistedForecastInputManifestService
from app.services.recommendation_research_model_execution_receipt_service import (
    RecommendationResearchModelExecutionReceiptService,
)


class TrustedResearchRunner(Protocol):
    def predict(self, *, model_bytes: bytes, inputs: list[dict[str, Any]]) -> dict[str, Any]: ...


class RecommendationResearchModelExecutorService:
    """Observe a trusted deployment runner before specification persistence.

    No HTTP endpoint, executable deserialization, model training or receipt minting.
    The deployment owns runner selection and artifact-hash pinning. This is only
    one component of the future v2 execution/specification/receipt workflow.
    """

    def __init__(
        self, *, runner: TrustedResearchRunner,
        manifest_service: PersistedForecastInputManifestService | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._runner = runner
        self._manifest = manifest_service or PersistedForecastInputManifestService()
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    def execute(
        self, *, specification: dict[str, Any], model_bytes: bytes,
        pinned_artifact_hash: str,
    ) -> dict[str, Any]:
        original_specification = specification
        specification_digest = self._hash(specification)
        # A caller/runner closure may retain the original dictionary. Never
        # compare observed output against a contract mutable during inference.
        specification = json.loads(json.dumps(specification, allow_nan=False))
        # Treat model bytes as data only. Never load pickle, eval or import a
        # module selected by model metadata. Hash the very bytes passed to runner.
        if not isinstance(model_bytes, bytes) or not 0 < len(model_bytes) <= 10_000_000:
            raise ValueError("Se requieren bytes de modelo, limitados a 10 MB.")
        artifact_hash = hashlib.sha256(model_bytes).hexdigest()
        if not isinstance(pinned_artifact_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", pinned_artifact_hash):
            raise ValueError("El deployment debe fijar un SHA-256 de artefacto válido.")
        if artifact_hash != pinned_artifact_hash:
            raise ValueError("Los bytes cargados no coinciden con el artefacto fijado.")
        try:
            model = json.loads(model_bytes, object_pairs_hook=self._unique_object)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("El artefacto del runner debe ser JSON de datos válido.") from exc
        if not isinstance(model, dict) or model.get("metric") != "total_return":
            raise ValueError("El runner requiere un contrato de modelo total_return explícito.")
        self._hash(model)  # Reject JSON NaN/Infinity before invoking trusted code.
        for field in ("name", "version"):
            value = model.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Falta model.{field}.")
            RecommendationResearchModelExecutionReceiptService()._assert_model_allowed(value)
        horizon = model.get("horizonSeconds")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ValueError("El modelo requiere horizonSeconds entero positivo.")
        snapshot = self._manifest.materialize_specification(specification)
        if horizon != specification["horizonSeconds"]:
            raise ValueError("El horizonte ejecutable no coincide con la specification.")
        inputs = snapshot["inputs"]
        input_snapshot_hash = self._hash(inputs)
        available_at = self._time(specification["forecastEvidence"]["availableAt"])
        started_at = self._time(self._now())
        latest_input = max(self._time(item["evidence"]["availableAt"]) for item in inputs)
        if not latest_input <= started_at <= available_at:
            raise ValueError("La ejecución no respeta la disponibilidad PIT/forecast.")
        output = self._runner.predict(model_bytes=model_bytes, inputs=inputs)
        completed_at = self._time(self._now())
        if self._hash(original_specification) != specification_digest:
            raise ValueError("La specification cambió durante la ejecución del runner.")
        if not started_at <= completed_at <= available_at:
            raise ValueError("El runner terminó tarde o el reloj retrocedió.")
        if self._hash(inputs) != input_snapshot_hash:
            raise ValueError("El runner modificó el snapshot de inputs.")
        if not isinstance(output, dict) or set(output) != {"metric", "expectedValue"} or output.get("metric") != "total_return":
            raise ValueError("El output observado requiere total_return y expectedValue.")
        value = output["expectedValue"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("El output observado debe ser numérico finito.")
        try:
            value = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError("El output observado debe ser numérico finito.") from exc
        if not math.isfinite(value):
            raise ValueError("El output observado debe ser numérico finito.")
        if value != specification["expectedValue"]:
            raise ValueError("El output observado no coincide con la previsión prospectiva.")
        observed_output = {"metric": "total_return", "expectedValue": float(value)}
        core = {
            "artifactVersion": "research-model-execution-observation-v1",
            "executionId": str(uuid4()),
            "specificationHash": snapshot["specificationHash"],
            "inputManifestHash": snapshot["inputManifestHash"],
            "inputSnapshotHash": input_snapshot_hash,
            "model": {"name": model["name"], "version": model["version"], "artifactHash": artifact_hash},
            "startedAt": started_at.isoformat(),
            "executedAt": completed_at.isoformat(),
            "output": observed_output,
            "outputHash": self._hash(observed_output),
        }
        observation = {
            **core, "observationHash": self._hash(core),
            "productionEligible": False, "productionLearningEligible": False,
            "automaticProductionPromotion": False, "automaticTrading": False,
        }
        return self.validate_observation(
            observation=observation, specification=specification, model_bytes=model_bytes,
        )

    def validate_observation(
        self, *, observation: dict[str, Any], specification: dict[str, Any],
        model_bytes: bytes,
    ) -> dict[str, Any]:
        """Revalidate bindings for trusted persistence; not an origin attestation."""
        if not isinstance(observation, dict) or observation.get("artifactVersion") != "research-model-execution-observation-v1":
            raise ValueError("Observación de ejecución incompatible.")
        core_keys = (
            "artifactVersion", "executionId", "specificationHash", "inputManifestHash",
            "inputSnapshotHash", "model", "startedAt", "executedAt", "output", "outputHash",
        )
        if observation.get("observationHash") != self._hash({key: observation.get(key) for key in core_keys}):
            raise ValueError("La observación fue modificada después de ejecutar el modelo.")
        for flag in ("productionEligible", "productionLearningEligible", "automaticProductionPromotion", "automaticTrading"):
            if observation.get(flag) is not False:
                raise ValueError("La observación intentó activar autoridad productiva.")
        if not isinstance(observation.get("executionId"), str) or not observation["executionId"].strip():
            raise ValueError("La observación perdió executionId.")
        snapshot = self._manifest.materialize_specification(specification)
        for field in ("specificationHash", "inputManifestHash"):
            if observation.get(field) != snapshot[field]:
                raise ValueError("La observación no corresponde a la specification/manifiesto.")
        if observation.get("inputSnapshotHash") != self._hash(snapshot["inputs"]):
            raise ValueError("La observación no corresponde a los payloads PIT originales.")
        if not isinstance(model_bytes, bytes) or not 0 < len(model_bytes) <= 10_000_000:
            raise ValueError("Faltan bytes del modelo observado.")
        try:
            model = json.loads(model_bytes, object_pairs_hook=self._unique_object)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Bytes de modelo JSON inválidos.") from exc
        if not isinstance(model, dict) or model.get("metric") != "total_return" or model.get("horizonSeconds") != specification["horizonSeconds"]:
            raise ValueError("El contrato del modelo observado no coincide con la previsión.")
        self._hash(model)
        if isinstance(model["horizonSeconds"], bool) or not isinstance(model["horizonSeconds"], int):
            raise ValueError("El horizonte del modelo observado debe ser entero.")
        for field in ("name", "version"):
            if not isinstance(model.get(field), str) or not model[field].strip():
                raise ValueError("El modelo observado perdió su identidad.")
            RecommendationResearchModelExecutionReceiptService()._assert_model_allowed(model[field])
        expected_model = {"name": model.get("name"), "version": model.get("version"), "artifactHash": hashlib.sha256(model_bytes).hexdigest()}
        if observation.get("model") != expected_model:
            raise ValueError("La observación no corresponde a los bytes del modelo.")
        expected_output = {"metric": "total_return", "expectedValue": float(specification["expectedValue"])}
        if observation.get("output") != expected_output or observation.get("outputHash") != self._hash(expected_output) or observation.get("outputHash") != self._hash(observation.get("output")):
            raise ValueError("La observación no corresponde al output de la previsión.")
        start, end = self._time(observation.get("startedAt")), self._time(observation.get("executedAt"))
        latest = max(self._time(item["evidence"]["availableAt"]) for item in snapshot["inputs"])
        if not latest <= start <= end <= self._time(specification["forecastEvidence"]["availableAt"]):
            raise ValueError("La observación viola el orden temporal PIT.")
        return json.loads(json.dumps(observation, allow_nan=False))

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("El artefacto JSON contiene claves duplicadas.")
            result[key] = value
        return result

    @staticmethod
    def _time(value: object) -> datetime:
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("Timestamp de ejecución inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Los timestamps deben incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")).hexdigest()
