from __future__ import annotations

from datetime import datetime, time, timezone
import math
from typing import Any, Mapping

from app.repositories.recommendation_macro_pit_observation_repository import (
    RecommendationMacroPitObservationRepository,
)
from app.services.recommendation_macro_pit_observation_service import (
    RecommendationMacroPitObservationService,
)


class RecommendationMacroPitImportService:
    """Normalize ALFRED vintage observations into persisted PIT evidence."""

    def __init__(
        self,
        repository: RecommendationMacroPitObservationRepository | None = None,
        artifact_service: RecommendationMacroPitObservationService | None = None,
    ) -> None:
        self._artifact_service = artifact_service or RecommendationMacroPitObservationService()
        self._repository = repository or RecommendationMacroPitObservationRepository(
            service=self._artifact_service
        )

    def import_fred_alfred_payload(
        self,
        *,
        series_id: str,
        payload: Mapping[str, Any],
        as_of: datetime,
        unit: str = "provider_native",
    ) -> dict[str, Any]:
        as_of_utc = self._aware_utc(as_of, "as_of")
        normalized_series = str(series_id or "").strip().upper()
        if not normalized_series:
            raise ValueError("series_id es obligatorio.")
        raw_observations = payload.get("observations")
        if not isinstance(raw_observations, list):
            raise ValueError("ALFRED payload no contiene observations válidas.")

        imported: list[str] = []
        skipped_missing = 0
        for index, raw in enumerate(raw_observations):
            if not isinstance(raw, Mapping):
                raise ValueError(f"observations[{index}] debe ser un objeto.")
            date_text = str(raw.get("date") or "").strip()
            realtime_start = str(raw.get("realtime_start") or "").strip()
            value_text = str(raw.get("value") or "").strip()
            if not date_text or not realtime_start:
                raise ValueError("Cada observación ALFRED debe incluir date y realtime_start.")
            if value_text in {"", "."}:
                skipped_missing += 1
                continue
            try:
                numeric = float(value_text)
            except ValueError as exc:
                raise ValueError("ALFRED devolvió un valor no numérico.") from exc
            if not math.isfinite(numeric):
                raise ValueError("ALFRED devolvió un valor no finito.")

            observed_at = self._date_utc(date_text, f"observations[{index}].date")
            available_at = self._date_utc(
                realtime_start,
                f"observations[{index}].realtime_start",
            )
            if available_at > as_of_utc:
                raise ValueError("ALFRED payload contiene una revisión posterior al as_of solicitado.")
            source_ref = f"FRED:{normalized_series}:{date_text}:vintage:{realtime_start}"
            artifact = self._artifact_service.build_artifact(
                series_id=normalized_series,
                value=numeric,
                observed_at=observed_at,
                available_at=available_at,
                source_provider="fred_alfred",
                source_ref=source_ref,
                unit=unit,
            )
            record = self._repository.append(artifact=artifact)
            imported.append(str(record["observation_key"]))

        return {
            "module": "macro_pit_import",
            "seriesId": normalized_series,
            "asOf": as_of_utc.isoformat(),
            "importedCount": len(imported),
            "skippedMissingCount": skipped_missing,
            "observationKeys": imported,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "source": "fred_alfred_server_side_only",
                "vintageTimestamp": "realtime_start_used_as_available_at",
                "lookahead": "future_vintages_fail_closed",
                "missingValues": "dot_or_empty_skipped_not_imputed",
            },
        }

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _date_utc(value: str, field: str) -> datetime:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{field} debe usar YYYY-MM-DD.") from exc
        return datetime.combine(parsed, time.min, tzinfo=timezone.utc)
