from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from app.models.normalized_data import NormalizedDatum


@dataclass(frozen=True)
class ConfidenceAssessment:
    metric: str
    confidence_score: float
    agreement_score: float
    source_quality_score: float
    dispersion_score: float
    sources_used: tuple[str, ...]
    observations_used: int
    has_discrepancy: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "confidence_score": self.confidence_score,
            "agreement_score": self.agreement_score,
            "source_quality_score": self.source_quality_score,
            "dispersion_score": self.dispersion_score,
            "sources_used": list(self.sources_used),
            "observations_used": self.observations_used,
            "has_discrepancy": self.has_discrepancy,
        }


class DataConfidenceService:
    """Build a transparent confidence score from comparable source observations."""

    def assess(
        self,
        observations: Iterable[NormalizedDatum],
        *,
        discrepancy_threshold_pct: float = 5.0,
    ) -> ConfidenceAssessment:
        items = list(observations)
        if not items:
            raise ValueError("At least one observation is required.")
        if discrepancy_threshold_pct < 0:
            raise ValueError("discrepancy_threshold_pct must be non-negative.")

        metric = items[0].metric
        if any(item.metric != metric for item in items):
            raise ValueError("All observations must refer to the same metric.")

        self._validate_comparison_context(items)

        source_ids = [item.provenance.source_id for item in items]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError(
                "Confidence assessment requires at most one comparable observation "
                "per source; select the canonical source observation first."
            )

        source_quality_values = [
            item.quality_score if item.quality_score is not None else 50.0
            for item in items
        ]
        source_quality_score = sum(source_quality_values) / len(source_quality_values)

        numeric_values = [
            float(item.value)
            for item in items
            if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
        ]

        if len(numeric_values) <= 1:
            dispersion_pct = 0.0
            agreement_score = 100.0
        else:
            center = median(numeric_values)
            scale = abs(center) if abs(center) > 1e-12 else max(
                max(abs(value) for value in numeric_values),
                1.0,
            )
            max_deviation = max(abs(value - center) for value in numeric_values)
            dispersion_pct = (max_deviation / scale) * 100.0
            agreement_score = max(
                0.0,
                100.0 - min(dispersion_pct * 4.0, 100.0),
            )

        diversity_bonus = min(len(set(source_ids)) - 1, 3) * 3.0
        confidence_score = (
            source_quality_score * 0.6
            + agreement_score * 0.4
            + diversity_bonus
        )
        confidence_score = round(max(0.0, min(confidence_score, 100.0)), 2)

        return ConfidenceAssessment(
            metric=metric,
            confidence_score=confidence_score,
            agreement_score=round(agreement_score, 2),
            source_quality_score=round(source_quality_score, 2),
            dispersion_score=round(
                max(0.0, 100.0 - min(dispersion_pct, 100.0)),
                2,
            ),
            sources_used=tuple(sorted(set(source_ids))),
            observations_used=len(items),
            has_discrepancy=dispersion_pct > discrepancy_threshold_pct,
        )

    def _validate_comparison_context(self, items: list[NormalizedDatum]) -> None:
        first = items[0]
        expected = self._comparison_context(first)
        for item in items[1:]:
            if self._comparison_context(item) != expected:
                raise ValueError(
                    "All observations must share data_kind, entity_id, unit, currency, "
                    "and effective_at before confidence can be compared."
                )

    def _comparison_context(
        self,
        item: NormalizedDatum,
    ) -> tuple[str, str | None, str | None, str | None, str | None]:
        return (
            item.data_kind,
            self._normalized_optional(item.entity_id),
            self._normalized_optional(item.unit),
            self._normalized_optional(item.currency),
            self._normalized_optional(item.provenance.effective_at),
        )

    @staticmethod
    def _normalized_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None
