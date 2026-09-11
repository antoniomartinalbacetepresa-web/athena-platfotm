from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Iterable

from app.repositories.corporate_action_repository import CorporateActionRepository


@dataclass(frozen=True)
class CorporateActionReconciliationEvent:
    action_type: str
    effective_at: str
    status: str
    providers_present: tuple[str, ...]
    providers_missing: tuple[str, ...]
    values_by_provider: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class CorporateActionReconciliationReport:
    instrument_id: int
    source_providers: tuple[str, ...]
    knowledge_cutoff: datetime
    events: tuple[CorporateActionReconciliationEvent, ...]

    @property
    def agreed_event_count(self) -> int:
        return sum(1 for event in self.events if event.status == "agreed")

    @property
    def conflict_event_count(self) -> int:
        return sum(1 for event in self.events if event.status == "conflict")

    @property
    def incomplete_event_count(self) -> int:
        return sum(1 for event in self.events if event.status == "incomplete")

    @property
    def reconciled(self) -> bool:
        return bool(self.events) and all(event.status == "agreed" for event in self.events)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "instrumentId": self.instrument_id,
            "sourceProviders": list(self.source_providers),
            "knowledgeCutoff": self.knowledge_cutoff.isoformat(),
            "eventCount": len(self.events),
            "agreedEventCount": self.agreed_event_count,
            "conflictEventCount": self.conflict_event_count,
            "incompleteEventCount": self.incomplete_event_count,
            "reconciled": self.reconciled,
            "automaticCanonicalization": False,
            "events": [
                {
                    "actionType": event.action_type,
                    "effectiveAt": event.effective_at,
                    "status": event.status,
                    "providersPresent": list(event.providers_present),
                    "providersMissing": list(event.providers_missing),
                    "valuesByProvider": event.values_by_provider,
                }
                for event in self.events
            ],
            "warning": (
                "La reconciliación compara únicamente información visible en el "
                "knowledge cutoff. Un conflicto o una fuente ausente impide considerar "
                "la acción corporativa reconciliada y nunca autoriza canonicalización "
                "automática."
            ),
        }


class CorporateActionReconciliationService:
    """Cross-provider PIT reconciliation for dividends and splits.

    The service is intentionally diagnostic. It never writes a canonical event
    and never resolves disagreements automatically. Each provider is queried
    through the PIT-aware repository at the requested knowledge cutoff.
    """

    _VALID_TYPES = {"dividend", "split"}

    def __init__(
        self,
        repository: CorporateActionRepository | None = None,
        *,
        numeric_tolerance: float = 1e-9,
    ) -> None:
        if not math.isfinite(numeric_tolerance) or numeric_tolerance < 0:
            raise ValueError("numeric_tolerance debe ser finito y no negativo.")
        self._repository = repository if repository is not None else CorporateActionRepository()
        self._numeric_tolerance = float(numeric_tolerance)

    def reconcile(
        self,
        *,
        instrument_id: int,
        source_providers: Iterable[str],
        knowledge_cutoff: datetime,
    ) -> CorporateActionReconciliationReport:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
            raise ValueError("knowledge_cutoff debe incluir zona horaria.")

        providers = self._normalize_providers(source_providers)
        if len(providers) < 2:
            raise ValueError("Se requieren al menos dos proveedores distintos.")

        latest_by_provider: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        all_keys: set[tuple[str, str]] = set()

        for provider in providers:
            rows = self._repository.list_for_instrument(
                instrument_id,
                source_provider=provider,
                knowledge_cutoff=knowledge_cutoff,
            )
            latest: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                action_type = str(row.get("action_type", "")).strip().lower()
                effective_at = str(row.get("effective_at", "")).strip()
                retrieved_at = str(row.get("retrieved_at", "")).strip()
                if action_type not in self._VALID_TYPES or not effective_at or not retrieved_at:
                    raise RuntimeError("Corporate action persistida con contrato inválido.")
                key = (action_type, effective_at)
                previous = latest.get(key)
                if previous is None or retrieved_at > str(previous["retrieved_at"]):
                    latest[key] = dict(row)
                all_keys.add(key)
            latest_by_provider[provider] = latest

        events: list[CorporateActionReconciliationEvent] = []
        for action_type, effective_at in sorted(all_keys, key=lambda value: (value[1], value[0])):
            key = (action_type, effective_at)
            present = tuple(provider for provider in providers if key in latest_by_provider[provider])
            missing = tuple(provider for provider in providers if key not in latest_by_provider[provider])
            values = {
                provider: self._public_value(latest_by_provider[provider][key])
                for provider in present
            }

            if missing:
                status = "incomplete"
            elif self._all_equal(tuple(values[provider] for provider in present)):
                status = "agreed"
            else:
                status = "conflict"

            events.append(
                CorporateActionReconciliationEvent(
                    action_type=action_type,
                    effective_at=effective_at,
                    status=status,
                    providers_present=present,
                    providers_missing=missing,
                    values_by_provider=values,
                )
            )

        return CorporateActionReconciliationReport(
            instrument_id=instrument_id,
            source_providers=providers,
            knowledge_cutoff=knowledge_cutoff,
            events=tuple(events),
        )

    def _normalize_providers(self, values: Iterable[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            provider = str(value or "").strip()
            if not provider:
                raise ValueError("source_providers no acepta valores vacíos.")
            if provider in seen:
                raise ValueError("source_providers no acepta proveedores duplicados.")
            seen.add(provider)
            normalized.append(provider)
        return tuple(normalized)

    def _public_value(self, row: dict[str, Any]) -> dict[str, Any]:
        action_type = str(row["action_type"]).lower()
        if action_type == "dividend":
            return {
                "cashAmount": float(row["cash_amount"]),
                "currency": (
                    str(row["currency"]).strip().upper()
                    if row.get("currency") is not None
                    else None
                ),
            }
        return {"splitRatio": float(row["split_ratio"])}

    def _all_equal(self, values: tuple[dict[str, Any], ...]) -> bool:
        if not values:
            return False
        reference = values[0]
        return all(self._value_equal(reference, candidate) for candidate in values[1:])

    def _value_equal(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left.keys() != right.keys():
            return False
        for key in left:
            left_value = left[key]
            right_value = right[key]
            if isinstance(left_value, float) and isinstance(right_value, float):
                if not math.isclose(
                    left_value,
                    right_value,
                    rel_tol=self._numeric_tolerance,
                    abs_tol=self._numeric_tolerance,
                ):
                    return False
            elif left_value != right_value:
                return False
        return True
