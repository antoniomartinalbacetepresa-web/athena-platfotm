from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from app.repositories.recommendation_macro_pit_observation_repository import RecommendationMacroPitObservationRepository
from app.services.recommendation_research_evaluation_specification_service import RecommendationResearchEvaluationSpecificationService


class PersistedMacroForecastInputService:
    """Resolve existing macro records, not caller-declared hashes or timestamps."""

    PREFIX = "urn:athena:macro-pit:"

    def __init__(self, repository: RecommendationMacroPitObservationRepository | None = None):
        self._repository = repository or RecommendationMacroPitObservationRepository()

    def resolve(
        self, *, observation_keys: list[str], knowledge_cutoff: datetime,
        forecast_available_at: datetime,
    ) -> list[dict[str, str]]:
        cutoff = self._aware(knowledge_cutoff, "knowledge_cutoff")
        forecast_at = self._aware(forecast_available_at, "forecast_available_at")
        if forecast_at < cutoff:
            raise ValueError("La previsión con inputs persistidos no puede anteceder al corte del ciclo.")
        if not isinstance(observation_keys, list) or not 1 <= len(observation_keys) <= 200:
            raise ValueError("Se requieren entre 1 y 200 observaciones macro persistidas.")
        keys = [str(key).strip().lower() for key in observation_keys]
        if any(re.fullmatch(r"[0-9a-f]{64}", key) is None for key in keys):
            raise ValueError("observationKey debe ser SHA-256 hexadecimal válido.")
        if len(set(keys)) != len(keys):
            raise ValueError("Observaciones macro duplicadas.")
        inputs = []
        for key in sorted(keys):
            record = self._repository.get_by_key(observation_key=key)
            artifact = record["artifact"]
            # Do not hide a forbidden upstream reference behind the internal URN.
            RecommendationResearchEvaluationSpecificationService()._assert_source_allowed(artifact["sourceRef"])
            published_at = self._iso(artifact["availableAt"], "macro.availableAt")
            persisted_at = self._iso(record["created_at"], "macro.created_at")
            if published_at > cutoff or persisted_at > cutoff:
                raise ValueError("La observación macro no estaba publicada y persistida al corte del ciclo.")
            # Bind the exact validated payload AND its physical persistence time.
            content = {"artifact": artifact, "persistedAt": persisted_at.isoformat()}
            content_hash = hashlib.sha256(json.dumps(
                content, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")).hexdigest()
            inputs.append({
                "source": artifact["sourceProvider"],
                "sourceRef": self.PREFIX + key,
                "availableAt": max(published_at, persisted_at).isoformat(),
                "contentHash": content_hash,
            })
        return inputs

    def verify_specification(self, artifact: dict[str, Any]) -> None:
        inputs = artifact.get("inputEvidence")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("Falta el manifiesto de inputs macro persistidos.")
        keys = []
        for item in inputs:
            ref = item.get("sourceRef") if isinstance(item, dict) else None
            if not isinstance(ref, str) or not ref.startswith(self.PREFIX):
                raise ValueError("El manifiesto persistido macro no admite referencias no resolubles.")
            keys.append(ref[len(self.PREFIX):])
        rebuilt = self.resolve(
            observation_keys=keys,
            knowledge_cutoff=self._iso(artifact.get("cycleAsOf"), "cycleAsOf"),
            forecast_available_at=self._iso(artifact.get("forecastEvidence", {}).get("availableAt"), "forecast.availableAt"),
        )
        if rebuilt != inputs:
            raise ValueError("El manifiesto no coincide con los inputs macro persistidos originales.")

    @staticmethod
    def uses_persisted_macro_inputs(artifact: dict[str, Any]) -> bool:
        return any(
            isinstance(item, dict) and isinstance(item.get("sourceRef"), str)
            and item["sourceRef"].startswith(PersistedMacroForecastInputService.PREFIX)
            for item in artifact.get("inputEvidence", [])
        )

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _iso(cls, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return cls._aware(parsed, field)
