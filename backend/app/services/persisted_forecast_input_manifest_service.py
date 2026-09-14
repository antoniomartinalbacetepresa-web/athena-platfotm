from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.persisted_macro_forecast_input_service import PersistedMacroForecastInputService
from app.services.persisted_market_forecast_input_service import PersistedMarketForecastInputService


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
        return sorted(inputs, key=lambda item: (item["availableAt"], item["source"], item["sourceRef"], item["contentHash"]))

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
