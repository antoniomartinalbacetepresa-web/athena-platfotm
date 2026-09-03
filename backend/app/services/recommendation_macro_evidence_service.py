from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.normalized_data_repository import NormalizedDataRepository


@dataclass(frozen=True)
class RecommendationMacroEvidence:
    status: str
    symbol: str
    as_of: str
    observation_count: int
    observations: tuple[dict[str, Any], ...]
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "asOf": self.as_of,
            "observationCount": self.observation_count,
            "observations": [dict(item) for item in self.observations],
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "failClosed": True,
                "pointInTime": True,
                "requiresAvailableAt": True,
                "requiresRetrievedAtByCutoff": True,
                "normalizedPersistedEvidenceOnly": True,
                "directLiveApiReplayForbidden": True,
                "directionalScoreAssigned": False,
                "thresholdCalibrated": False,
                "noAdvice": True,
            },
        }


class RecommendationMacroEvidenceService:
    """Read persisted macro observations visible to ATHENA at a PIT cutoff.

    This service deliberately does not call live macro APIs and does not turn macro
    observations into a directional score. Its job is to establish a truthful,
    replayable macro-evidence contract that later calibration can consume.
    """

    _METRIC_PREFIX = "macro."

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()
        self._repository = NormalizedDataRepository(self._database)

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
    ) -> RecommendationMacroEvidence:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)
        cutoff = as_of_utc.isoformat()

        self._repository.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM normalized_data_observations
                WHERE metric LIKE ?
                  AND available_at IS NOT NULL
                  AND available_at <= ?
                  AND retrieved_at <= ?
                ORDER BY
                    COALESCE(effective_at, published_at, retrieved_at) DESC,
                    COALESCE(available_at, published_at, retrieved_at) DESC,
                    id DESC
                """,
                (f"{self._METRIC_PREFIX}%", cutoff, cutoff),
            ).fetchall()

        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        invalid_count = 0
        for row in rows:
            raw = dict(row)
            identity = (
                str(raw.get("metric") or "").strip(),
                str(raw.get("entity_id") or "").strip(),
                str(raw.get("source_id") or "").strip(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            normalized = self._normalize_row(raw, as_of=as_of_utc)
            if normalized is None:
                invalid_count += 1
                continue
            selected.append(normalized)

        if invalid_count:
            return RecommendationMacroEvidence(
                status="invalid_evidence",
                symbol=normalized_symbol,
                as_of=cutoff,
                observation_count=len(selected),
                observations=tuple(selected),
                production_eligible=False,
                reason=(
                    "Se detectó evidencia macro persistida que viola el contrato "
                    "numérico o PIT; ATHENA la rechaza y no la usa como contexto."
                ),
            )
        if not selected:
            return RecommendationMacroEvidence(
                status="no_data",
                symbol=normalized_symbol,
                as_of=cutoff,
                observation_count=0,
                observations=(),
                production_eligible=False,
                reason=(
                    "No hay observaciones macro normalizadas que ATHENA hubiera "
                    "recuperado y tenido disponibles en este corte point-in-time."
                ),
            )
        return RecommendationMacroEvidence(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            as_of=cutoff,
            observation_count=len(selected),
            observations=tuple(selected),
            production_eligible=False,
            reason=(
                "Contexto macro PIT disponible con procedencia verificable. No se "
                "asigna dirección, score ni umbral hasta calibración fuera de muestra."
            ),
        )

    def _normalize_row(
        self,
        row: dict[str, Any],
        *,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        metric = str(row.get("metric") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        if not metric.startswith(self._METRIC_PREFIX) or not source_id:
            return None

        try:
            value = json.loads(str(row.get("value_json")))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric_value = float(value)
        if not isfinite(numeric_value):
            return None

        available_at = self._optional_aware_datetime(row.get("available_at"))
        retrieved_at = self._optional_aware_datetime(row.get("retrieved_at"))
        if (
            available_at is None
            or retrieved_at is None
            or available_at > as_of
            or retrieved_at > as_of
        ):
            return None

        for key in ("quality_score", "confidence_score"):
            score = row.get(key)
            if score is None:
                continue
            if isinstance(score, bool):
                return None
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                return None
            if not isfinite(numeric_score) or not 0.0 <= numeric_score <= 100.0:
                return None

        return {
            "metric": metric,
            "entityId": self._optional_text(row.get("entity_id")),
            "value": numeric_value,
            "unit": self._optional_text(row.get("unit")),
            "sourceId": source_id,
            "effectiveAt": self._optional_text(row.get("effective_at")),
            "publishedAt": self._optional_text(row.get("published_at")),
            "availableAt": available_at.isoformat(),
            "retrievedAt": retrieved_at.isoformat(),
            "sourceVersion": self._optional_text(row.get("source_version")),
            "sourceUrl": self._optional_text(row.get("source_url")),
            "qualityScore": self._optional_finite_score(row.get("quality_score")),
            "confidenceScore": self._optional_finite_score(
                row.get("confidence_score")
            ),
        }

    @staticmethod
    def _optional_finite_score(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if isfinite(numeric) else None

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_aware_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
