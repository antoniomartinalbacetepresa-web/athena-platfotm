from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Mapping

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository


@dataclass(frozen=True)
class CorporateActionCoverageReport:
    eligible_instrument_count: int
    action_bearing_instrument_count: int
    event_count: int
    agreed_event_count: int
    conflict_event_count: int
    incomplete_event_count: int
    source_providers: tuple[str, ...]
    independent_provider_families: tuple[str, ...]
    unclassified_source_providers: tuple[str, ...]

    @property
    def agreement_coverage(self) -> float:
        if self.event_count <= 0:
            return 0.0
        return self.agreed_event_count / self.event_count

    @property
    def cross_provider_reconciliation_ready(self) -> bool:
        return (
            self.event_count > 0
            and len(self.independent_provider_families) >= 2
            and self.agreed_event_count == self.event_count
            and self.conflict_event_count == 0
            and self.incomplete_event_count == 0
            and self.agreement_coverage >= 1.0
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "eligibleInstrumentCount": self.eligible_instrument_count,
            "actionBearingInstrumentCount": self.action_bearing_instrument_count,
            "eventCount": self.event_count,
            "agreedEventCount": self.agreed_event_count,
            "conflictEventCount": self.conflict_event_count,
            "incompleteEventCount": self.incomplete_event_count,
            "agreementCoverage": self.agreement_coverage,
            "sourceProviders": list(self.source_providers),
            "independentProviderFamilies": list(self.independent_provider_families),
            "unclassifiedSourceProviders": list(self.unclassified_source_providers),
            "crossProviderReconciliationReady": self.cross_provider_reconciliation_ready,
            "automaticCanonicalization": False,
            "productionIndependenceClaimed": False,
            "warning": (
                "La cobertura exige que cada corporate action visible al knowledge cutoff "
                "coincida entre al menos dos familias de proveedor configuradas. La "
                "clasificación técnica de familias no sustituye una verificación externa "
                "de independencia contractual/operativa y nunca autoriza canonicalización "
                "automática."
            ),
        }


class CorporateActionCoverageService:
    """Aggregate PIT cross-provider evidence without selecting a canonical source.

    Only provider identifiers explicitly mapped to different source families count
    as independent technical evidence. A registered adapter is necessary but not
    sufficient for readiness: the report remains blocked until observations from
    at least two families are actually persisted and agree event by event.
    """

    DEFAULT_PROVIDER_FAMILIES: Mapping[str, str] = {
        "yahoo": "yahoo",
        "alpha_vantage": "alpha_vantage",
    }
    _EXCLUDED_TYPES = ("etf", "fund")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        provider_families: Mapping[str, str] | None = None,
        numeric_tolerance: float = 1e-9,
    ) -> None:
        if not math.isfinite(numeric_tolerance) or numeric_tolerance < 0:
            raise ValueError("numeric_tolerance debe ser finito y no negativo.")
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)
        families = (
            provider_families
            if provider_families is not None
            else self.DEFAULT_PROVIDER_FAMILIES
        )
        self._provider_families = self._normalize_provider_families(families)
        self._numeric_tolerance = float(numeric_tolerance)

    def get_report(self, *, as_of: datetime) -> CorporateActionCoverageReport:
        cutoff = self._aware_utc(as_of, "as_of")
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM instruments
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(instrument_type, 'unknown')))
                      NOT IN ('etf', 'fund')
                ORDER BY id ASC
                """
            ).fetchall()
        instrument_ids = tuple(int(row["id"]) for row in rows)

        source_providers: set[str] = set()
        trusted_families: set[str] = set()
        unclassified: set[str] = set()
        action_bearing_instrument_count = 0
        agreed = 0
        conflicts = 0
        incomplete = 0

        for instrument_id in instrument_ids:
            actions = self._repository.list_for_instrument(
                instrument_id,
                knowledge_cutoff=cutoff,
            )
            if not actions:
                continue
            action_bearing_instrument_count += 1

            latest_by_event_provider: dict[
                tuple[str, str], dict[str, dict[str, Any]]
            ] = {}
            for row in actions:
                provider = str(row.get("source_provider") or "").strip()
                if not provider:
                    raise RuntimeError("Corporate action persistida sin source_provider.")
                source_providers.add(provider)
                family = self._provider_families.get(provider)
                if family is None:
                    unclassified.add(provider)
                else:
                    trusted_families.add(family)

                key = (
                    str(row.get("action_type") or "").strip().lower(),
                    str(row.get("effective_at") or "").strip(),
                )
                if key[0] not in {"dividend", "split"} or not key[1]:
                    raise RuntimeError("Corporate action persistida con contrato inválido.")
                latest_by_provider = latest_by_event_provider.setdefault(key, {})
                previous = latest_by_provider.get(provider)
                if previous is None or str(row["retrieved_at"]) > str(previous["retrieved_at"]):
                    latest_by_provider[provider] = dict(row)

            for latest_by_provider in latest_by_event_provider.values():
                classified_rows: list[tuple[str, dict[str, Any]]] = []
                event_families: set[str] = set()
                for provider, row in latest_by_provider.items():
                    family = self._provider_families.get(provider)
                    if family is None:
                        continue
                    event_families.add(family)
                    classified_rows.append((family, row))

                if len(event_families) < 2:
                    incomplete += 1
                    continue

                values = [self._public_value(row) for _, row in classified_rows]
                if self._all_equal(values):
                    agreed += 1
                else:
                    conflicts += 1

        event_count = agreed + conflicts + incomplete
        return CorporateActionCoverageReport(
            eligible_instrument_count=len(instrument_ids),
            action_bearing_instrument_count=action_bearing_instrument_count,
            event_count=event_count,
            agreed_event_count=agreed,
            conflict_event_count=conflicts,
            incomplete_event_count=incomplete,
            source_providers=tuple(sorted(source_providers)),
            independent_provider_families=tuple(sorted(trusted_families)),
            unclassified_source_providers=tuple(sorted(unclassified)),
        )

    def _normalize_provider_families(
        self,
        values: Mapping[str, str],
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_provider, raw_family in values.items():
            provider = str(raw_provider or "").strip()
            family = str(raw_family or "").strip()
            if not provider or not family:
                raise ValueError("provider_families no acepta claves o familias vacías.")
            if provider in normalized:
                raise ValueError("provider_families contiene proveedores duplicados.")
            normalized[provider] = family
        return normalized

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

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

    def _all_equal(self, values: list[dict[str, Any]]) -> bool:
        if len(values) < 2:
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
