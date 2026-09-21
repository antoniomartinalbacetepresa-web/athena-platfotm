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
        return self.agreed_event_count / self.event_count if self.event_count > 0 else 0.0

    @property
    def cross_provider_reconciliation_ready(self) -> bool:
        return (
            self.event_count > 0
            and len(self.independent_provider_families) >= 2
            and not self.unclassified_source_providers
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
                "coincida entre al menos dos familias de proveedor configuradas, incluya "
                "unidades económicas completas y que no exista provenance de proveedor sin "
                "clasificar. La clasificación técnica no demuestra independencia operativa y "
                "nunca autoriza canonicalización automática."
            ),
        }


class CorporateActionCoverageService:
    DEFAULT_PROVIDER_FAMILIES: Mapping[str, str] = {
        "yahoo": "yahoo",
        "alpha_vantage": "alpha_vantage",
    }
    _EXCLUDED_TYPES = ("etf", "fund")

    def __init__(self, database: AthenaDatabase | None = None, *, provider_families: Mapping[str, str] | None = None, numeric_tolerance: float = 1e-9) -> None:
        if not math.isfinite(numeric_tolerance) or numeric_tolerance < 0:
            raise ValueError("numeric_tolerance debe ser finito y no negativo.")
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)
        self._provider_families = self._normalize_provider_families(provider_families or self.DEFAULT_PROVIDER_FAMILIES)
        self._numeric_tolerance = float(numeric_tolerance)

    def get_report(self, *, as_of: datetime) -> CorporateActionCoverageReport:
        cutoff = self._aware_utc(as_of, "as_of")
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute("SELECT id FROM instruments WHERE is_active = 1 AND LOWER(TRIM(COALESCE(instrument_type, 'unknown'))) NOT IN ('etf', 'fund') ORDER BY id ASC").fetchall()
        instrument_ids = tuple(int(row["id"]) for row in rows)
        providers: set[str] = set()
        families_seen: set[str] = set()
        unclassified: set[str] = set()
        bearing = agreed = conflicts = incomplete = 0

        for instrument_id in instrument_ids:
            actions = self._repository.list_for_instrument(instrument_id, knowledge_cutoff=cutoff)
            if not actions:
                continue
            bearing += 1
            events: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
            latest: dict[tuple[tuple[str, str], str], datetime] = {}
            for row in actions:
                provider = str(row.get("source_provider") or "").strip()
                if not provider:
                    raise RuntimeError("Corporate action persistida sin source_provider.")
                providers.add(provider)
                family = self._provider_families.get(provider)
                if family is None:
                    unclassified.add(provider)
                else:
                    families_seen.add(family)
                action_type = str(row.get("action_type") or "").strip().lower()
                if action_type not in {"dividend", "split"}:
                    raise RuntimeError("Corporate action persistida con contrato inválido.")
                effective = self._parse_aware_datetime(row.get("effective_at"), field="effective_at")
                retrieved = self._parse_aware_datetime(row.get("retrieved_at"), field="retrieved_at")
                if retrieved > cutoff:
                    raise RuntimeError("Corporate action persistida viola el knowledge cutoff PIT.")
                key = (action_type, effective.isoformat())
                snapshot_key = (key, provider)
                if snapshot_key not in latest or retrieved > latest[snapshot_key]:
                    events.setdefault(key, {})[provider] = dict(row)
                    latest[snapshot_key] = retrieved

            for by_provider in events.values():
                # Agreement on a number without its economic unit is not usable
                # reconciliation evidence. In particular, equal dividend amounts with
                # unknown currency must remain incomplete rather than becoming "ready".
                if any(not self._has_complete_economic_value(row) for row in by_provider.values()):
                    incomplete += 1
                    continue
                by_family: dict[str, list[dict[str, Any]]] = {}
                for provider, row in by_provider.items():
                    family = self._provider_families.get(provider)
                    if family is not None:
                        by_family.setdefault(family, []).append(row)
                if len(by_family) < 2:
                    incomplete += 1
                    continue
                family_values: list[dict[str, Any]] = []
                family_conflict = False
                for rows_for_family in by_family.values():
                    values = [self._public_value(row) for row in rows_for_family]
                    if not self._all_equal_or_single(values):
                        family_conflict = True
                        break
                    family_values.append(values[0])
                if family_conflict:
                    conflicts += 1
                elif self._all_equal(family_values):
                    agreed += 1
                else:
                    conflicts += 1

        return CorporateActionCoverageReport(
            eligible_instrument_count=len(instrument_ids), action_bearing_instrument_count=bearing,
            event_count=agreed + conflicts + incomplete, agreed_event_count=agreed,
            conflict_event_count=conflicts, incomplete_event_count=incomplete,
            source_providers=tuple(sorted(providers)), independent_provider_families=tuple(sorted(families_seen)),
            unclassified_source_providers=tuple(sorted(unclassified)),
        )

    def _has_complete_economic_value(self, row: dict[str, Any]) -> bool:
        action_type = str(row.get("action_type") or "").strip().lower()
        if action_type == "dividend":
            amount = row.get("cash_amount")
            currency = str(row.get("currency") or "").strip().upper()
            return (
                isinstance(amount, (int, float))
                and not isinstance(amount, bool)
                and math.isfinite(float(amount))
                and float(amount) > 0
                and len(currency) == 3
                and currency.isalpha()
            )
        if action_type == "split":
            ratio = row.get("split_ratio")
            return (
                isinstance(ratio, (int, float))
                and not isinstance(ratio, bool)
                and math.isfinite(float(ratio))
                and float(ratio) > 0
            )
        return False

    def _normalize_provider_families(self, values: Mapping[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_provider, raw_family in values.items():
            provider, family = str(raw_provider or "").strip(), str(raw_family or "").strip()
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

    def _parse_aware_datetime(self, value: Any, *, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"Corporate action persistida con {field} inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"Corporate action persistida con {field} sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _public_value(self, row: dict[str, Any]) -> dict[str, Any]:
        if str(row["action_type"]).lower() == "dividend":
            return {"cashAmount": float(row["cash_amount"]), "currency": str(row["currency"]).strip().upper()}
        return {"splitRatio": float(row["split_ratio"])}

    def _all_equal_or_single(self, values: list[dict[str, Any]]) -> bool:
        return bool(values) and all(self._value_equal(values[0], value) for value in values[1:])

    def _all_equal(self, values: list[dict[str, Any]]) -> bool:
        return len(values) >= 2 and all(self._value_equal(values[0], value) for value in values[1:])

    def _value_equal(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left.keys() != right.keys():
            return False
        for key, left_value in left.items():
            right_value = right[key]
            if isinstance(left_value, float) and isinstance(right_value, float):
                if not math.isclose(left_value, right_value, rel_tol=self._numeric_tolerance, abs_tol=self._numeric_tolerance):
                    return False
            elif left_value != right_value:
                return False
        return True
