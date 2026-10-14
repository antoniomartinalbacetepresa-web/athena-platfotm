from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from app.services.persisted_macro_forecast_input_service import PersistedMacroForecastInputService
from app.services.persisted_market_forecast_input_service import PersistedMarketForecastInputService
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)


class PersistedForecastInputManifestService:
    """Compose and re-verify supported persisted PIT input families for forecast v3."""

    def __init__(
        self,
        macro_service: PersistedMacroForecastInputService | None = None,
        market_service: PersistedMarketForecastInputService | None = None,
    ) -> None:
        self._macro = macro_service or PersistedMacroForecastInputService()
        self._market = market_service or PersistedMarketForecastInputService()

    def resolve(
        self,
        *,
        macro_observation_keys: list[str] | None,
        market_selections: list[dict[str, object]] | None,
        knowledge_cutoff: datetime,
        forecast_available_at: datetime,
    ) -> list[dict[str, str]]:
        macro_keys = list(macro_observation_keys or [])
        market = list(market_selections or [])
        if not macro_keys and not market:
            raise ValueError("Se requiere al menos un input PIT persistido macro o de mercado.")
        if len(macro_keys) + len(market) > 200:
            raise ValueError("El manifiesto PIT no puede superar 200 inputs persistidos.")

        inputs: list[dict[str, str]] = []
        if macro_keys:
            inputs.extend(
                self._macro.resolve(
                    observation_keys=macro_keys,
                    knowledge_cutoff=knowledge_cutoff,
                    forecast_available_at=forecast_available_at,
                )
            )
        if market:
            inputs.extend(
                self._market.resolve(
                    selections=market,
                    knowledge_cutoff=knowledge_cutoff,
                    forecast_available_at=forecast_available_at,
                )
            )
        refs = [item["sourceRef"] for item in inputs]
        hashes = [item["contentHash"] for item in inputs]
        if len(set(refs)) != len(refs):
            raise ValueError("El manifiesto PIT contiene referencias duplicadas.")
        if len(set(hashes)) != len(hashes):
            raise ValueError("El manifiesto PIT contiene contenido duplicado.")
        return sorted(inputs, key=lambda item: item["sourceRef"])

    def verify_specification(self, artifact: dict[str, Any]) -> None:
        inputs = artifact.get("inputEvidence")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("Falta inputEvidence PIT persistido.")
        supported = 0
        if self._macro.uses_persisted_macro_inputs(artifact):
            self._macro.verify_specification(artifact)
            supported += sum(
                1 for item in inputs
                if isinstance(item, dict)
                and isinstance(item.get("sourceRef"), str)
                and item["sourceRef"].startswith(self._macro.PREFIX)
            )
        if self._market.uses_persisted_market_inputs(artifact):
            self._market.verify_specification(artifact)
            supported += sum(
                1 for item in inputs
                if isinstance(item, dict)
                and isinstance(item.get("sourceRef"), str)
                and item["sourceRef"].startswith(self._market.PREFIX)
            )
        if supported != len(inputs):
            raise ValueError("El manifiesto persistido contiene inputs no resolubles por ATHENA.")

    def materialize_specification(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Load a detached execution-input snapshot matching a sealed v3 manifest.

        Each family's materializer hashes and returns the very same loaded content;
        there is no verify-then-read-again window. This does not execute a model.
        """
        validator = RecommendationResearchEvaluationSpecificationService()
        validated = validator.validate_artifact(artifact)
        if validated["artifactVersion"] != validator.PIT_INPUT_ARTIFACT_VERSION:
            raise ValueError("La materialización de inputs requiere specification v3.")
        inputs = validated["inputEvidence"]
        cutoff = datetime.fromisoformat(validated["cycleAsOf"])
        forecast_at = datetime.fromisoformat(validated["forecastEvidence"]["availableAt"])
        macro_keys = []
        market_selections = []
        for item in inputs:
            ref = item["sourceRef"]
            if ref.startswith(self._macro.PREFIX):
                macro_keys.append(ref[len(self._macro.PREFIX):])
            elif ref.startswith(self._market.PREFIX):
                market_selections.append(self._market._decode_selector(ref[len(self._market.PREFIX):]))
            else:
                raise ValueError("El manifiesto contiene inputs no materializables por ATHENA.")
        if len(inputs) > 200:
            raise ValueError("El manifiesto PIT no puede superar 200 inputs persistidos.")
        snapshot = []
        if macro_keys:
            snapshot.extend(self._macro.materialize(
                observation_keys=macro_keys, knowledge_cutoff=cutoff,
                forecast_available_at=forecast_at,
            ))
        if market_selections:
            snapshot.extend(self._market.materialize(
                selections=market_selections, knowledge_cutoff=cutoff,
                forecast_available_at=forecast_at,
            ))
        snapshot.sort(key=lambda item: item["evidence"]["sourceRef"])
        if [item["evidence"] for item in snapshot] != inputs:
            raise ValueError("El contenido materializado no coincide con el manifiesto sellado.")
        # Detach mutable payloads from repository/cache-owned objects before a
        # future executor consumes them. Preserve canonical hash serialization.
        snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
        return {
            "specificationHash": validated["specificationHash"],
            "inputManifestHash": hashlib.sha256(json.dumps(
                inputs, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")).hexdigest(),
            "inputs": snapshot,
        }
