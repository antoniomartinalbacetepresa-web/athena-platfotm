from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)


class PersistedMarketForecastInputService:
    """Resolve exact persisted market rows into re-verifiable v3 input evidence."""

    PREFIX = "urn:athena:market-pit:"

    def __init__(self, repository: MarketObservationRepository | None = None) -> None:
        self._repository = repository or MarketObservationRepository()

    def resolve(
        self,
        *,
        selections: list[dict[str, object]],
        knowledge_cutoff: datetime,
        forecast_available_at: datetime,
    ) -> list[dict[str, str]]:
        cutoff = self._aware(knowledge_cutoff, "knowledge_cutoff")
        forecast_at = self._aware(forecast_available_at, "forecast_available_at")
        if forecast_at < cutoff:
            raise ValueError("La previsión con inputs de mercado persistidos no puede anteceder al corte del ciclo.")
        if not isinstance(selections, list) or not 1 <= len(selections) <= 200:
            raise ValueError("Se requieren entre 1 y 200 observaciones de mercado persistidas.")

        inputs: list[dict[str, str]] = []
        seen_refs: set[str] = set()
        for selection in selections:
            if not isinstance(selection, dict):
                raise ValueError("Cada selección de mercado debe ser un objeto.")
            instrument_id = self._positive_int(selection.get("instrumentId"), "instrumentId")
            provider = self._text(selection.get("sourceProvider"), "sourceProvider")
            observed_at = self._iso(selection.get("observedAt"), "observedAt")
            RecommendationResearchEvaluationSpecificationService()._assert_source_allowed(provider)
            rows = self._repository.list_for_instrument(
                instrument_id,
                source_provider=provider,
                knowledge_cutoff=cutoff,
                observed_from=observed_at,
                observed_to=observed_at,
            )
            exact = [row for row in rows if self._iso(row.get("observed_at"), "market.observed_at") == observed_at]
            if len(exact) != 1:
                raise ValueError("La observación de mercado seleccionada no existe de forma única al corte PIT.")
            row = exact[0]
            retrieved_at = self._iso(row.get("retrieved_at"), "market.retrieved_at")
            if retrieved_at > cutoff or observed_at > cutoff:
                raise ValueError("La observación de mercado no estaba observada y persistida al corte del ciclo.")
            if retrieved_at > forecast_at:
                raise ValueError("La observación de mercado fue persistida después de generar la previsión.")

            selector = {
                "instrumentId": instrument_id,
                "sourceProvider": provider,
                "observedAt": observed_at.isoformat(),
            }
            source_ref = self.PREFIX + self._encode_selector(selector)
            if source_ref in seen_refs:
                raise ValueError("Observaciones de mercado duplicadas.")
            seen_refs.add(source_ref)
            content_hash = hashlib.sha256(
                json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
            ).hexdigest()
            inputs.append(
                {
                    "source": provider,
                    "sourceRef": source_ref,
                    "availableAt": retrieved_at.isoformat(),
                    "contentHash": content_hash,
                }
            )
        return sorted(inputs, key=lambda item: item["sourceRef"])

    def verify_specification(self, artifact: dict[str, Any]) -> None:
        inputs = artifact.get("inputEvidence")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("Falta el manifiesto de inputs de mercado persistidos.")
        market_inputs = [
            item for item in inputs
            if isinstance(item, dict)
            and isinstance(item.get("sourceRef"), str)
            and item["sourceRef"].startswith(self.PREFIX)
        ]
        if not market_inputs:
            return
        selections = [self._decode_selector(str(item["sourceRef"])[len(self.PREFIX):]) for item in market_inputs]
        rebuilt = self.resolve(
            selections=selections,
            knowledge_cutoff=self._iso(artifact.get("cycleAsOf"), "cycleAsOf"),
            forecast_available_at=self._iso(
                artifact.get("forecastEvidence", {}).get("availableAt"),
                "forecast.availableAt",
            ),
        )
        if rebuilt != market_inputs:
            raise ValueError("El manifiesto no coincide con los inputs de mercado persistidos originales.")

    @classmethod
    def uses_persisted_market_inputs(cls, artifact: dict[str, Any]) -> bool:
        return any(
            isinstance(item, dict)
            and isinstance(item.get("sourceRef"), str)
            and item["sourceRef"].startswith(cls.PREFIX)
            for item in artifact.get("inputEvidence", [])
        )

    @staticmethod
    def _encode_selector(selector: dict[str, object]) -> str:
        raw = json.dumps(selector, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_selector(value: str) -> dict[str, object]:
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception as exc:
            raise ValueError("sourceRef de mercado persistido no es resoluble.") from exc
        if not isinstance(decoded, dict):
            raise ValueError("sourceRef de mercado persistido no contiene un selector válido.")
        return decoded

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _iso(cls, value: object, field: str) -> datetime:
        if isinstance(value, datetime):
            return cls._aware(value, field)
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return cls._aware(parsed, field)

    @staticmethod
    def _text(value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if normalized <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return normalized
