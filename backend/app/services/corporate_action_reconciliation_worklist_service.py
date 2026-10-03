from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_coverage_service import CorporateActionCoverageService


@dataclass(frozen=True)
class CorporateActionReconciliationItem:
    instrument_id: int
    symbol: str
    action_type: str
    effective_at: str
    observed_providers: tuple[str, ...]
    observed_provider_families: tuple[str, ...]
    unclassified_providers: tuple[str, ...]
    missing_independent_family_count: int
    suggested_provider: str | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "actionType": self.action_type,
            "effectiveAt": self.effective_at,
            "observedProviders": list(self.observed_providers),
            "observedProviderFamilies": list(self.observed_provider_families),
            "unclassifiedProviders": list(self.unclassified_providers),
            "requiredIndependentFamilyCount": 2,
            "missingIndependentFamilyCount": self.missing_independent_family_count,
            "suggestedProvider": self.suggested_provider,
            "automaticCanonicalization": False,
        }


@dataclass(frozen=True)
class CorporateActionReconciliationWorklist:
    as_of: datetime
    total_incomplete_event_count: int
    limit: int
    offset: int
    items: tuple[CorporateActionReconciliationItem, ...]

    def to_api_dict(self) -> dict[str, Any]:
        selected = len(self.items)
        return {
            "status": "reconciliation_worklist_only",
            "asOf": self.as_of.astimezone(timezone.utc).isoformat(),
            "totalIncompleteEventCount": self.total_incomplete_event_count,
            "selectedCount": selected,
            "limit": self.limit,
            "offset": self.offset,
            "hasMore": self.offset + selected < self.total_incomplete_event_count,
            "items": [item.to_api_dict() for item in self.items],
            "policy": {
                "minimumIndependentProviderFamilies": 2,
                "automaticCanonicalization": False,
                "productionIndependenceClaimed": False,
                "automaticReadinessPromotion": False,
                "automaticTrading": False,
            },
            "warning": (
                "La worklist identifica evidencia PIT que aún carece de dos familias "
                "técnicamente independientes. Una sugerencia de proveedor no demuestra "
                "independencia contractual u operativa y no autoriza canonicalización."
            ),
        }


class CorporateActionReconciliationWorklistService:
    """List exact PIT corporate-action events still missing a second source family."""

    _EXCLUDED_TYPES = ("etf", "fund")

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        provider_families: Mapping[str, str] | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)
        families = (
            provider_families
            if provider_families is not None
            else CorporateActionCoverageService.DEFAULT_PROVIDER_FAMILIES
        )
        self._provider_families = self._normalize_provider_families(families)

    def get_worklist(
        self,
        *,
        as_of: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> CorporateActionReconciliationWorklist:
        cutoff = self._aware_utc(as_of)
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        self._database.initialize()
        with self._database.connect() as connection:
            instruments = connection.execute(
                """
                SELECT id, symbol
                FROM instruments
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(instrument_type, 'unknown')))
                      NOT IN ('etf', 'fund')
                ORDER BY id ASC
                """
            ).fetchall()

        incomplete: list[CorporateActionReconciliationItem] = []
        for instrument in instruments:
            instrument_id = int(instrument["id"])
            symbol = str(instrument["symbol"] or "").strip().upper()
            actions = self._repository.list_for_instrument(
                instrument_id,
                knowledge_cutoff=cutoff,
            )
            latest_by_event_provider: dict[
                tuple[str, str], dict[str, dict[str, Any]]
            ] = {}
            for raw in actions:
                row = dict(raw)
                provider = str(row.get("source_provider") or "").strip()
                if not provider:
                    raise RuntimeError("Corporate action persistida sin source_provider.")
                key = (
                    str(row.get("action_type") or "").strip().lower(),
                    str(row.get("effective_at") or "").strip(),
                )
                if key[0] not in {"dividend", "split"} or not key[1]:
                    raise RuntimeError("Corporate action persistida con contrato inválido.")
                by_provider = latest_by_event_provider.setdefault(key, {})
                previous = by_provider.get(provider)
                if previous is None or str(row["retrieved_at"]) > str(previous["retrieved_at"]):
                    by_provider[provider] = row

            for (action_type, effective_at), latest_by_provider in sorted(
                latest_by_event_provider.items()
            ):
                providers = tuple(sorted(latest_by_provider))
                families = tuple(
                    sorted(
                        {
                            family
                            for provider in providers
                            if (family := self._provider_families.get(provider)) is not None
                        }
                    )
                )
                unclassified = tuple(
                    provider
                    for provider in providers
                    if provider not in self._provider_families
                )
                if len(families) >= 2:
                    continue
                incomplete.append(
                    CorporateActionReconciliationItem(
                        instrument_id=instrument_id,
                        symbol=symbol,
                        action_type=action_type,
                        effective_at=effective_at,
                        observed_providers=providers,
                        observed_provider_families=families,
                        unclassified_providers=unclassified,
                        missing_independent_family_count=max(0, 2 - len(families)),
                        suggested_provider=self._suggest_provider(families),
                    )
                )

        total = len(incomplete)
        page = tuple(incomplete[offset : offset + limit])
        return CorporateActionReconciliationWorklist(
            as_of=cutoff,
            total_incomplete_event_count=total,
            limit=limit,
            offset=offset,
            items=page,
        )

    def _suggest_provider(self, families: tuple[str, ...]) -> str | None:
        observed = set(families)
        if "yahoo" in observed and "alpha_vantage" not in observed:
            return "alpha_vantage"
        if "alpha_vantage" in observed and "yahoo" not in observed:
            return "yahoo"
        return None

    def _normalize_provider_families(self, values: Mapping[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_provider, raw_family in values.items():
            provider = str(raw_provider or "").strip()
            family = str(raw_family or "").strip()
            if not provider or not family:
                raise ValueError("provider_families no acepta claves o familias vacías.")
            normalized[provider] = family
        return normalized

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
