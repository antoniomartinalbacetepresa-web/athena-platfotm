from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
import re
from statistics import median
from typing import Any

from app.services.recommendation_research_forecast_error_oos_summary_service import (
    RecommendationResearchForecastErrorOosSummaryService,
)


class RecommendationResearchForecastErrorOosSummaryIntegrityService:
    """Deep semantic validator for persisted OOS forecast-error summaries."""

    def __init__(self) -> None:
        self._base = RecommendationResearchForecastErrorOosSummaryService()

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        validated = self._base.validate_artifact(artifact)
        rows = validated.get("rows")
        error_hashes = validated.get("errorHashes")
        if not isinstance(rows, list) or not rows or len(rows) > 5000:
            raise ValueError("OOS forecast summary contiene rows inválidas.")
        if not isinstance(error_hashes, list) or len(error_hashes) != len(rows):
            raise ValueError("OOS forecast summary perdió correspondencia rows/errorHashes.")
        if validated.get("observationCount") != len(rows):
            raise ValueError("observationCount no coincide con rows.")

        summary_as_of = self._aware_iso(validated.get("asOf"), "asOf")
        method = self._text(validated.get("method"), "method")
        horizon = self._positive_int(validated.get("horizonSeconds"), "horizonSeconds")

        seen_errors: set[str] = set()
        seen_specs: set[str] = set()
        seen_outcomes: set[str] = set()
        seen_cycles: set[str] = set()
        instruments: list[str] = []
        signed_values: list[float] = []
        absolute_values: list[float] = []
        squared_values: list[float] = []
        normalized_periods: list[tuple[datetime, datetime]] = []
        row_hashes: list[str] = []

        previous_sort_key: tuple[str, str, str] | None = None
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"rows[{index}] debe ser un objeto.")
            error_hash = self._sha256(row.get("errorHash"), f"rows[{index}].errorHash")
            spec_hash = self._sha256(row.get("specificationHash"), f"rows[{index}].specificationHash")
            outcome_hash = self._sha256(row.get("outcomeHash"), f"rows[{index}].outcomeHash")
            cycle_hash = self._sha256(row.get("cycleHash"), f"rows[{index}].cycleHash")
            if error_hash in seen_errors or spec_hash in seen_specs or outcome_hash in seen_outcomes or cycle_hash in seen_cycles:
                raise ValueError("OOS forecast summary contiene identidades duplicadas.")
            seen_errors.add(error_hash)
            seen_specs.add(spec_hash)
            seen_outcomes.add(outcome_hash)
            seen_cycles.add(cycle_hash)

            if self._text(row.get("method"), f"rows[{index}].method") != method:
                raise ValueError("OOS forecast summary mezcla métodos dentro de rows.")
            if self._positive_int(row.get("horizonSeconds"), f"rows[{index}].horizonSeconds") != horizon:
                raise ValueError("OOS forecast summary mezcla horizontes dentro de rows.")
            instrument_id = self._text(row.get("instrumentId"), f"rows[{index}].instrumentId")
            instruments.append(instrument_id)
            self._text(row.get("symbol"), f"rows[{index}].symbol")

            period_start = self._aware_iso(row.get("periodStart"), f"rows[{index}].periodStart")
            period_end = self._aware_iso(row.get("periodEnd"), f"rows[{index}].periodEnd")
            if period_end <= period_start or period_end > summary_as_of:
                raise ValueError("OOS forecast summary contiene periodo inválido o posterior al asOf.")
            if int((period_end - period_start).total_seconds()) != horizon:
                raise ValueError("Periodo de row no coincide con horizonSeconds.")
            normalized_periods.append((period_start, period_end))

            expected = self._finite(row.get("expectedValue"), f"rows[{index}].expectedValue")
            realized = self._finite(row.get("realizedValue"), f"rows[{index}].realizedValue")
            signed = self._finite(row.get("signedError"), f"rows[{index}].signedError")
            absolute = self._finite(row.get("absoluteError"), f"rows[{index}].absoluteError")
            squared = self._finite(row.get("squaredError"), f"rows[{index}].squaredError")
            if not math.isclose(signed, realized - expected, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Row signedError no reconcilia con realized-expected.")
            if not math.isclose(absolute, abs(signed), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Row absoluteError no reconcilia con signedError.")
            if not math.isclose(squared, signed * signed, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Row squaredError no reconcilia con signedError.")
            signed_values.append(signed)
            absolute_values.append(absolute)
            squared_values.append(squared)
            row_hashes.append(error_hash)

            sort_key = (period_end.isoformat(), instrument_id, error_hash)
            if previous_sort_key is not None and sort_key < previous_sort_key:
                raise ValueError("rows no conserva el orden canónico.")
            previous_sort_key = sort_key

        if error_hashes != row_hashes:
            raise ValueError("errorHashes no coincide exactamente con el orden canónico de rows.")

        counts = Counter(instruments)
        if validated.get("distinctInstrumentCount") != len(counts):
            raise ValueError("distinctInstrumentCount no coincide con rows.")
        if validated.get("maximumObservationsPerInstrument") != max(counts.values(), default=0):
            raise ValueError("maximumObservationsPerInstrument no coincide con rows.")

        overlap_pairs = 0
        for index, (left_start, left_end) in enumerate(normalized_periods):
            for right_start, right_end in normalized_periods[index + 1 :]:
                if max(left_start, right_start) < min(left_end, right_end):
                    overlap_pairs += 1
        if validated.get("overlappingPeriodPairCount") != overlap_pairs:
            raise ValueError("overlappingPeriodPairCount no coincide con rows.")

        count = len(rows)
        expected_metrics = {
            "meanSignedError": sum(signed_values) / count,
            "meanAbsoluteError": sum(absolute_values) / count,
            "rootMeanSquaredError": math.sqrt(sum(squared_values) / count),
            "medianAbsoluteError": median(absolute_values),
        }
        metrics = validated.get("metrics")
        assert isinstance(metrics, dict)
        for name, expected_value in expected_metrics.items():
            actual = self._finite(metrics.get(name), f"metrics.{name}")
            if not math.isclose(actual, expected_value, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"metrics.{name} no reconcilia con rows.")
        return validated

    @staticmethod
    def _aware_iso(value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text
