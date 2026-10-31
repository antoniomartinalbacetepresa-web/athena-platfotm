from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonalizationReadinessReport:
    configured_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    optional_context_complete: bool

    @property
    def completion_ratio(self) -> float:
        total = len(self.configured_fields) + len(self.missing_fields)
        if total <= 0:
            return 0.0
        return len(self.configured_fields) / total

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "configuredFields": list(self.configured_fields),
            "missingFields": list(self.missing_fields),
            "completionRatio": self.completion_ratio,
            "optionalContextComplete": self.optional_context_complete,
            "automaticRecommendationOverrides": False,
            "productionEligible": False,
            "automaticTrading": False,
        }


class PersonalizationReadinessService:
    """Measures profile completeness without changing investment decisions.

    The four legacy fields remain the minimum persisted profile contract. The
    three richer context fields improve explainability/personalization but must
    never be treated as permission to override recommendation, weighting, or
    execution controls.
    """

    REQUIRED_FIELDS = (
        "riskTolerance",
        "investmentHorizonYears",
        "baseCurrency",
        "objective",
    )
    OPTIONAL_CONTEXT_FIELDS = (
        "experienceLevel",
        "liquidityNeed",
        "maxDrawdownTolerancePct",
    )
    ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_CONTEXT_FIELDS

    def evaluate(self, preferences: dict[str, Any] | None) -> PersonalizationReadinessReport:
        data = preferences or {}
        configured: list[str] = []
        missing: list[str] = []

        for field in self.ALL_FIELDS:
            value = data.get(field)
            if self._is_configured(value):
                configured.append(field)
            else:
                missing.append(field)

        optional_complete = all(
            field in configured for field in self.OPTIONAL_CONTEXT_FIELDS
        )
        return PersonalizationReadinessReport(
            configured_fields=tuple(configured),
            missing_fields=tuple(missing),
            optional_context_complete=optional_complete,
        )

    @staticmethod
    def _is_configured(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True
