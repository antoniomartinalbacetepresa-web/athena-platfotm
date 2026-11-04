from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_ALLOWED_KINDS = frozenset(
    {
        "earnings",
        "guidance",
        "regulatory",
        "product",
        "capital_allocation",
        "financing",
        "legal",
        "strategic",
        "macro",
    }
)


@dataclass(frozen=True)
class RecommendationCatalystInput:
    catalyst_id: str
    name: str
    kind: str
    expected_start: datetime
    expected_end: datetime
    defined_at: datetime
    definition_source: str
    definition_source_ref: str
    occurred_at: datetime | None = None
    occurrence_available_at: datetime | None = None
    occurrence_source: str | None = None
    occurrence_source_ref: str | None = None


@dataclass(frozen=True)
class RecommendationCatalystResult:
    catalyst_id: str
    name: str
    kind: str
    state: str
    timeliness: str
    expected_start: str
    expected_end: str
    defined_at: str
    definition_source: str
    definition_source_ref: str
    occurred_at: str | None
    occurrence_available_at: str | None
    occurrence_source: str | None
    occurrence_source_ref: str | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "catalystId": self.catalyst_id,
            "name": self.name,
            "kind": self.kind,
            "state": self.state,
            "timeliness": self.timeliness,
            "expectedStart": self.expected_start,
            "expectedEnd": self.expected_end,
            "definedAt": self.defined_at,
            "definitionSource": self.definition_source,
            "definitionSourceRef": self.definition_source_ref,
            "occurredAt": self.occurred_at,
            "occurrenceAvailableAt": self.occurrence_available_at,
            "occurrenceSource": self.occurrence_source,
            "occurrenceSourceRef": self.occurrence_source_ref,
        }


@dataclass(frozen=True)
class RecommendationCatalystDiagnostic:
    symbol: str
    as_of: str
    catalysts: tuple[RecommendationCatalystResult, ...]
    occurred_count: int
    pending_count: int
    missed_count: int
    delayed_count: int

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_ready",
            "symbol": self.symbol,
            "asOf": self.as_of,
            "catalysts": [item.to_api_dict() for item in self.catalysts],
            "occurredCount": self.occurred_count,
            "pendingCount": self.pending_count,
            "missedCount": self.missed_count,
            "delayedCount": self.delayed_count,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "reason": (
                "Estado PIT de catalizadores explícitos y trazables. Un catalizador retrasado "
                "o no observado exige reevaluación, pero no constituye por sí solo una orden de venta."
            ),
            "policy": {
                "temporal": "definition_and_occurrence_evidence_must_be_available_at_or_before_as_of",
                "provenance": "definitions_and_occurrences_require_explicit_sources",
                "states": "objective_expected_window_and_observed_occurrence_only",
                "missedCatalystAutomaticallyInvalidatesThesis": False,
                "interpretation": "catalyst_state_requires_reassessment_not_automatic_buy_sell",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationCatalystService:
    """Classify explicit PIT catalysts without converting them into investment advice."""

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        catalysts: tuple[RecommendationCatalystInput, ...],
    ) -> RecommendationCatalystDiagnostic:
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        cutoff = self._aware_utc(as_of, "as_of")
        if not isinstance(catalysts, tuple) or not catalysts:
            raise ValueError("catalysts debe contener al menos un catalizador explícito.")
        if len(catalysts) > 50:
            raise ValueError("catalysts no puede contener más de 50 elementos.")

        seen_ids: set[str] = set()
        results: list[RecommendationCatalystResult] = []
        for raw in catalysts:
            item = self._validate(raw, as_of=cutoff)
            if item.catalyst_id in seen_ids:
                raise ValueError("catalyst_id no puede repetirse.")
            seen_ids.add(item.catalyst_id)
            state, timeliness = self._state(item, as_of=cutoff)
            results.append(
                RecommendationCatalystResult(
                    catalyst_id=item.catalyst_id,
                    name=item.name,
                    kind=item.kind,
                    state=state,
                    timeliness=timeliness,
                    expected_start=item.expected_start.isoformat(),
                    expected_end=item.expected_end.isoformat(),
                    defined_at=item.defined_at.isoformat(),
                    definition_source=item.definition_source,
                    definition_source_ref=item.definition_source_ref,
                    occurred_at=item.occurred_at.isoformat() if item.occurred_at else None,
                    occurrence_available_at=(
                        item.occurrence_available_at.isoformat()
                        if item.occurrence_available_at
                        else None
                    ),
                    occurrence_source=item.occurrence_source,
                    occurrence_source_ref=item.occurrence_source_ref,
                )
            )

        occurred = sum(1 for item in results if item.state == "occurred")
        pending = sum(1 for item in results if item.state == "pending")
        missed = sum(1 for item in results if item.state == "missed")
        delayed = sum(1 for item in results if item.timeliness == "late")
        return RecommendationCatalystDiagnostic(
            symbol=normalized_symbol,
            as_of=cutoff.isoformat(),
            catalysts=tuple(results),
            occurred_count=occurred,
            pending_count=pending,
            missed_count=missed,
            delayed_count=delayed,
        )

    def _validate(
        self,
        value: RecommendationCatalystInput,
        *,
        as_of: datetime,
    ) -> RecommendationCatalystInput:
        if not isinstance(value, RecommendationCatalystInput):
            raise ValueError("Cada catalizador debe ser RecommendationCatalystInput.")
        catalyst_id = self._required_text(value.catalyst_id, "catalyst_id").lower()
        name = self._required_text(value.name, "name")
        kind = self._required_text(value.kind, "kind").lower()
        if kind not in _ALLOWED_KINDS:
            raise ValueError("kind no soportado para Catalyst research.")
        expected_start = self._aware_utc(value.expected_start, "expected_start")
        expected_end = self._aware_utc(value.expected_end, "expected_end")
        if expected_end < expected_start:
            raise ValueError("expected_end no puede ser anterior a expected_start.")
        defined_at = self._aware_utc(value.defined_at, "defined_at")
        if defined_at > as_of:
            raise ValueError("defined_at no puede ser posterior a as_of; evitar look-ahead es obligatorio.")
        definition_source = self._required_text(value.definition_source, "definition_source")
        definition_source_ref = self._required_text(
            value.definition_source_ref, "definition_source_ref"
        )

        occurrence_fields = (
            value.occurred_at,
            value.occurrence_available_at,
            value.occurrence_source,
            value.occurrence_source_ref,
        )
        has_any_occurrence = any(field is not None for field in occurrence_fields)
        has_all_occurrence = all(field is not None for field in occurrence_fields)
        if has_any_occurrence and not has_all_occurrence:
            raise ValueError("La evidencia de ocurrencia debe ser completa o estar totalmente ausente.")

        occurred_at: datetime | None = None
        occurrence_available_at: datetime | None = None
        occurrence_source: str | None = None
        occurrence_source_ref: str | None = None
        if has_all_occurrence:
            occurred_at = self._aware_utc(value.occurred_at, "occurred_at")  # type: ignore[arg-type]
            occurrence_available_at = self._aware_utc(
                value.occurrence_available_at, "occurrence_available_at"  # type: ignore[arg-type]
            )
            if occurrence_available_at > as_of:
                raise ValueError(
                    "occurrence_available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio."
                )
            if occurred_at > occurrence_available_at:
                raise ValueError("occurred_at no puede ser posterior a occurrence_available_at.")
            occurrence_source = self._required_text(value.occurrence_source, "occurrence_source")
            occurrence_source_ref = self._required_text(
                value.occurrence_source_ref, "occurrence_source_ref"
            )

        return RecommendationCatalystInput(
            catalyst_id=catalyst_id,
            name=name,
            kind=kind,
            expected_start=expected_start,
            expected_end=expected_end,
            defined_at=defined_at,
            definition_source=definition_source,
            definition_source_ref=definition_source_ref,
            occurred_at=occurred_at,
            occurrence_available_at=occurrence_available_at,
            occurrence_source=occurrence_source,
            occurrence_source_ref=occurrence_source_ref,
        )

    def _state(
        self,
        item: RecommendationCatalystInput,
        *,
        as_of: datetime,
    ) -> tuple[str, str]:
        if item.occurred_at is not None:
            if item.occurred_at < item.expected_start:
                return "occurred", "early"
            if item.occurred_at <= item.expected_end:
                return "occurred", "on_time"
            return "occurred", "late"
        if as_of <= item.expected_end:
            return "pending", "not_yet_determined"
        return "missed", "not_observed_by_expected_end"

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar semántica y provenance.")
        return text

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
